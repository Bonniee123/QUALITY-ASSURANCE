"""
Clustering must never take the server down because the PC is short of memory.

Loading the embedding model needs about 730 MB. On a PC whose RAM is full and
whose page file cannot grow (its drive is full), the load can crash the whole
Python process -- and clustering runs inside the web server. The model is now
only loaded when there is room for it; otherwise that run clusters with TF-IDF,
which it already did whenever embeddings were unavailable.
"""
import errno
import importlib.util
import os
import unittest
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from ai_processing import embedding_service as svc
from documents.models import Document
from qa_structure.models import AccreditationArea

HAS_SENTENCE_TRANSFORMERS = importlib.util.find_spec('sentence_transformers') is not None
PAGING_FILE_TOO_SMALL = OSError(
    'The paging file is too small for this operation to complete. (os error 1455)')


class _FakeModel:
    def encode(self, texts, **kwargs):
        import numpy as np
        return np.array([[float(len(t)), float(sum(map(ord, t)) % 997), 1.0] for t in texts])


class _CacheIsolation:
    """Each test starts with no model loaded and puts the real caches back after."""

    def setUp(self):
        super().setUp()
        self.saved = dict(svc._model_cache), svc._vector_cache.copy()
        svc._model_cache.clear()
        svc._vector_cache.clear()

    def tearDown(self):
        svc._model_cache.clear()
        svc._model_cache.update(self.saved[0])
        svc._vector_cache.clear()
        svc._vector_cache.update(self.saved[1])
        super().tearDown()


def _doc(title):
    return Document(title=title, document_type='Report', year=2026, extracted_text=f'{title} body')


@override_settings(AI_CLUSTER_EMBEDDING_MODEL='guard-test-model', AI_CLUSTER_EMBEDDING_MIN_FREE_MB=1536)
class MemoryGuardTests(_CacheIsolation, SimpleTestCase):

    def setUp(self):
        # Before the caches are touched: a skip in setUp means no tearDown.
        if not HAS_SENTENCE_TRANSFORMERS:
            self.skipTest('sentence-transformers not installed')
        super().setUp()

    def test_short_of_memory_the_model_is_not_loaded(self):
        with mock.patch.object(svc, '_free_memory_mb', return_value=400), \
                mock.patch.object(svc, '_load_model') as load, \
                self.assertLogs('ai_processing.embedding_service', 'WARNING') as logs:
            result = svc.compute_embedding_matrix([_doc('alpha'), _doc('beta')])
        self.assertIsNone(result, 'no embeddings: clustering uses TF-IDF')
        load.assert_not_called()
        self.assertIn('400 MB of memory free', logs.output[0])
        self.assertIn('TF-IDF', logs.output[0])

    def test_enough_memory_loads_it_as_before(self):
        with mock.patch.object(svc, '_free_memory_mb', return_value=4000), \
                mock.patch.object(svc, '_load_model', return_value=_FakeModel()) as load:
            result = svc.compute_embedding_matrix([_doc('alpha'), _doc('beta')])
        load.assert_called_once_with('guard-test-model')
        self.assertEqual(result.shape, (2, 3))

    def test_a_loaded_model_keeps_working_when_memory_runs_short(self):
        """Nothing new has to be loaded, so there is nothing to check."""
        svc._model_cache['guard-test-model'] = _FakeModel()
        with mock.patch.object(svc, '_free_memory_mb', return_value=100) as free:
            result = svc.compute_embedding_matrix([_doc('alpha')])
        self.assertEqual(result.shape, (1, 3))
        free.assert_not_called()

    def test_the_next_run_looks_again(self):
        """Short of memory is not remembered: once there is room, the model loads."""
        with mock.patch.object(svc, '_load_model', return_value=_FakeModel()) as load:
            with mock.patch.object(svc, '_free_memory_mb', return_value=400), \
                    self.assertLogs('ai_processing.embedding_service', 'WARNING'):
                self.assertIsNone(svc.compute_embedding_matrix([_doc('alpha')]))
            with mock.patch.object(svc, '_free_memory_mb', return_value=4000):
                self.assertIsNotNone(svc.compute_embedding_matrix([_doc('alpha')]))
        load.assert_called_once()

    def test_where_memory_cannot_be_measured_nothing_changes(self):
        with mock.patch.object(svc, '_free_memory_mb', return_value=None), \
                mock.patch.object(svc, '_load_model', return_value=_FakeModel()) as load:
            self.assertIsNotNone(svc.compute_embedding_matrix([_doc('alpha')]))
        load.assert_called_once()

    @override_settings(AI_CLUSTER_EMBEDDING_MIN_FREE_MB=0)
    def test_zero_turns_the_check_off(self):
        with mock.patch.object(svc, '_free_memory_mb', return_value=1) as free, \
                mock.patch.object(svc, '_load_model', return_value=_FakeModel()) as load:
            self.assertIsNotNone(svc.compute_embedding_matrix([_doc('alpha')]))
        free.assert_not_called()
        load.assert_called_once()

    def test_running_out_during_the_load_itself_still_falls_back(self):
        """The check passed but memory ran out anyway: a clean error, not a crash."""
        with mock.patch.object(svc, '_free_memory_mb', return_value=4000), \
                mock.patch.object(svc, '_load_model', side_effect=PAGING_FILE_TOO_SMALL), \
                self.assertLogs('ai_processing.embedding_service', 'WARNING'):
            self.assertIsNone(svc.compute_embedding_matrix([_doc('alpha')]))
        self.assertNotIn('guard-test-model', svc._model_cache, 'the next run tries again')


@unittest.skipUnless(HAS_SENTENCE_TRANSFORMERS, 'sentence-transformers not installed')
class LoadingTheModelTests(SimpleTestCase):

    def test_out_of_memory_is_not_retried_online(self):
        """Going online would only repeat the same load after a slow network check."""
        from sentence_transformers import SentenceTransformer  # noqa: F401
        with mock.patch('sentence_transformers.SentenceTransformer',
                        side_effect=PAGING_FILE_TOO_SMALL) as ctor:
            with self.assertRaises(OSError):
                svc._load_model('some-model')
        ctor.assert_called_once_with('some-model', local_files_only=True)

    def test_a_model_not_on_disk_is_still_fetched_online(self):
        from sentence_transformers import SentenceTransformer  # noqa: F401
        missing = OSError("We couldn't connect to 'https://huggingface.co' to load the files, "
                          "and couldn't find them in the cached files.")
        fake = _FakeModel()
        with mock.patch('sentence_transformers.SentenceTransformer',
                        side_effect=[missing, fake]) as ctor:
            self.assertIs(svc._load_model('some-model'), fake)
        self.assertEqual(ctor.call_args_list,
                         [mock.call('some-model', local_files_only=True), mock.call('some-model')])


class RecognisingOutOfMemoryTests(SimpleTestCase):

    def test_out_of_memory_errors(self):
        chained = RuntimeError('Error while deserializing header')
        chained.__cause__ = MemoryError()
        cases = {
            'MemoryError': MemoryError(),
            'page file too small, from Rust': PAGING_FILE_TOO_SMALL,
            'torch allocator': RuntimeError(
                '[enforce fail at alloc_cpu.cpp:114] DefaultCPUAllocator: not enough memory: '
                'you tried to allocate 1536000 bytes.'),
            'ENOMEM': OSError(errno.ENOMEM, 'Cannot allocate memory'),
            'caused by a MemoryError': chained,
        }
        for name, exc in cases.items():
            with self.subTest(name):
                self.assertTrue(svc._ran_out_of_memory(exc))

    @unittest.skipUnless(os.name == 'nt', 'Windows error codes')
    def test_windows_error_codes(self):
        for code in (8, 14, 1455):
            with self.subTest(code):
                self.assertTrue(svc._ran_out_of_memory(OSError(0, 'failed', None, code)))

    def test_other_errors_are_not_mistaken_for_it(self):
        cases = [
            FileNotFoundError('model.safetensors not found'),
            OSError("We couldn't connect to 'https://huggingface.co' to load the files."),
            ValueError('Unrecognized model configuration'),
        ]
        for exc in cases:
            with self.subTest(repr(exc)):
                self.assertFalse(svc._ran_out_of_memory(exc))


class PageFileGrowthTests(SimpleTestCase):
    """How far the system drive's page file can still grow, by Microsoft's rules."""

    RAM_MB = 16108          # this PC
    VOLUME_MB = 204799      # its C: drive

    def room(self, entry, current=958, active=958, volume=VOLUME_MB, free=597):
        return svc._page_file_growth_mb(entry, current, active, self.RAM_MB, volume, free)

    def test_a_nearly_full_drive_leaves_it_no_room(self):
        """This PC today: 597 MB free on C:."""
        self.assertEqual(self.room('c:\\pagefile.sys 0 0'), 0)

    def test_freeing_space_on_the_drive_gives_it_room(self):
        # Limited by an eighth of the drive (25,599 MB) less its current 958 MB.
        self.assertEqual(self.room('c:\\pagefile.sys 0 0', free=26 * 1024), 25599 - 958)

    def test_it_never_counts_the_drive_reserve(self):
        self.assertEqual(self.room('c:\\pagefile.sys 0 0', free=3000), 3000 - 1024)

    def test_windows_managing_every_drive_counts_as_system_managed(self):
        self.assertEqual(self.room('?:\\pagefile.sys', free=26 * 1024), 25599 - 958)

    def test_a_small_drive_caps_it_at_an_eighth(self):
        self.assertEqual(self.room('c:\\pagefile.sys 0 0', volume=65536, free=40000), 8192 - 958)

    def test_a_fixed_maximum_is_respected(self):
        self.assertEqual(
            self.room('c:\\pagefile.sys 1024 4096', current=1024, active=1024, free=50000), 3072)
        self.assertEqual(
            self.room('c:\\pagefile.sys 4096 4096', current=4096, active=4096, free=50000), 0)

    def test_a_page_file_not_in_use_gets_no_credit(self):
        self.assertEqual(self.room('c:\\pagefile.sys 0 0', active=0, free=50000), 0)

    def test_no_page_file_or_an_unreadable_setting_gets_no_credit(self):
        self.assertEqual(self.room(None, free=50000), 0)
        self.assertEqual(self.room('c:\\pagefile.sys 1024', free=50000), 0)
        self.assertEqual(self.room('c:\\pagefile.sys 0 0', current=0, free=50000), 0)


@unittest.skipUnless(os.name == 'nt', 'reads Windows memory figures')
class ThisPcTests(SimpleTestCase):

    def test_windows_reports_believable_figures(self):
        ram_mb, limit_mb, available_mb = svc._windows_memory()
        self.assertGreater(ram_mb, 0)
        self.assertGreater(limit_mb, 0)
        self.assertTrue(0 <= available_mb <= limit_mb)

    def test_the_guard_counts_at_least_what_is_free_now(self):
        _ram, _limit, available_mb = svc._windows_memory()
        self.assertGreaterEqual(svc._free_memory_mb(), available_mb - 512)

    def test_page_file_room_is_never_negative(self):
        ram_mb, limit_mb, _available = svc._windows_memory()
        self.assertGreaterEqual(svc._system_page_file_growth_mb(ram_mb, limit_mb), 0)


@override_settings(
    AI_CLUSTER_USE_EMBEDDINGS=True,
    AI_CLUSTER_HYBRID_METADATA=True,
    AI_CLUSTER_WITHIN_AREA=True,
    AI_CLUSTER_WITHIN_DOC_TYPE=True,
    AI_CLUSTER_EMBEDDING_MIN_FREE_MB=1536,
)
class ClusteringWhenShortOfMemoryTests(_CacheIsolation, TestCase):
    """End to end: the run completes, with TF-IDF, and never touches the model."""

    @classmethod
    def setUpTestData(cls):
        cls.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.area4, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IV', defaults={'area_name': 'Support to Students'})
        cls.user = User.objects.create_user('guard_uploader', password='x')
        faculty = ('faculty qualifications ranks development plan training workshop '
                   'professor instructor teaching load')
        research = ('research publication journal funding grant thesis dissertation '
                    'laboratory experiment methodology')
        for i in range(3):
            for text, area, name in ((faculty, cls.area2, 'Faculty'), (research, cls.area4, 'Research')):
                Document.objects.create(
                    title=f'{name} {i}', file_type='pdf', year=2026, document_type='Report',
                    extracted_text=f'{text} section {i}', qa_area=area.area_code, acc_area=area,
                    uploaded_by=cls.user,
                )

    def short_of_memory(self):
        return mock.patch.object(svc, '_free_memory_mb', return_value=300)

    def test_the_clustering_features_fall_back_to_tfidf(self):
        from ai_processing.cluster_features import build_clustering_matrix
        from ai_processing.clustering_text import clustering_input_text
        from ai_processing.smart_clustering import run_smart_clustering

        docs = list(Document.objects.order_by('pk'))
        texts = [clustering_input_text(d) for d in docs]
        with self.short_of_memory(), mock.patch.object(svc, '_load_model') as load, \
                self.assertLogs('ai_processing.embedding_service', 'WARNING'):
            matrix, features, backend = build_clustering_matrix(docs, texts)
        load.assert_not_called()
        self.assertEqual(backend, 'hybrid')
        self.assertEqual(matrix.shape[0], len(docs))

        result = run_smart_clustering(docs, matrix, features)
        by_area = {}
        for doc, label in zip(docs, result['labels']):
            by_area.setdefault(doc.acc_area_id, set()).add(label)
        self.assertEqual(len(by_area), 2)
        self.assertTrue(by_area[self.area2.pk].isdisjoint(by_area[self.area4.pk]))

    def test_the_full_pipeline_completes_and_labels_every_document(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        with self.short_of_memory(), mock.patch.object(svc, '_load_model') as load, \
                self.assertLogs('ai_processing.embedding_service', 'WARNING'):
            message = run_full_ai_pipeline(None)
        load.assert_not_called()
        self.assertIn('Document analysis complete', message)
        self.assertIn('hybrid', message)
        self.assertFalse(Document.objects.filter(cluster_label__isnull=True).exists())


@unittest.skipUnless(HAS_SENTENCE_TRANSFORMERS, 'sentence-transformers not installed')
@override_settings(AI_CLUSTER_EMBEDDING_MODEL='thread-test-model', AI_CLUSTER_EMBEDDING_MIN_FREE_MB=0)
class ModelRunsOnOneThreadTests(_CacheIsolation, SimpleTestCase):
    """
    PyTorch leaves a team of worker threads behind for every thread that calls
    into it. Clustering runs on a new thread after every upload, so the model
    must always run on the same one - otherwise each upload leaks ~70 MB.
    """

    def test_every_load_and_encode_runs_on_one_thread_whoever_calls(self):
        import threading

        seen = []

        class Recorder(_FakeModel):
            def encode(self, texts, **kwargs):
                seen.append(('encode', threading.get_ident()))
                return super().encode(texts, **kwargs)

        def load(_name):
            seen.append(('load', threading.get_ident()))
            return Recorder()

        with mock.patch.object(svc, '_load_model', side_effect=load):
            for i in range(4):
                worker = threading.Thread(target=svc.compute_embedding_matrix, args=([_doc(f'text {i}')],))
                worker.start()
                worker.join()
        self.assertEqual([kind for kind, _t in seen], ['load', 'encode', 'encode', 'encode', 'encode'])
        self.assertEqual(len({t for _k, t in seen}), 1, 'one thread for the model, whichever thread asked')
        self.assertNotIn(threading.get_ident(), {t for _k, t in seen})

    def test_an_error_on_the_model_thread_still_reaches_the_caller(self):
        with mock.patch.object(svc, '_load_model', side_effect=PAGING_FILE_TOO_SMALL), \
                self.assertLogs('ai_processing.embedding_service', 'WARNING'):
            self.assertIsNone(svc.compute_embedding_matrix([_doc('alpha')]))

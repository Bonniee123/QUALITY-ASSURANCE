"""
The AI result page's badge says how the clusters on screen were actually made.

Each document's AI Processing Result page shows its cluster number with a badge
naming the clustering method. After a run started by an upload -- a background
run, with no page session to write to -- the badge fell back to the settings and
said "Semantic embeddings", even when that run had clustered with TF-IDF because
the PC was short of memory. Every run that relabels the clusters now records the
method it used, and the badge reads that.
"""
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ai_processing import embedding_service
from ai_processing.dashboard_utils import get_clustering_engine_info
from documents.ai_pipeline import CLUSTERING_RUN_METRIC, run_full_ai_pipeline
from documents.models import Document, ProcessingMetric
from qa_structure.models import AccreditationArea

# The badge exactly as the template renders it, in each of its three existing forms.
EMBEDDING_BADGE = '<span class="badge badge-complete">Semantic embeddings</span>'
HYBRID_BADGE = '<span class="badge badge-suggested">Hybrid TF-IDF + metadata</span>'
TFIDF_BADGE = '<span class="badge badge-unmapped">TF-IDF keywords</span>'


def _fake_embeddings(documents):
    """Stand-in vectors (no model load in tests): one direction per subject."""
    return np.array([
        [1.0, 0.0, 0.05 * i] if d.title.startswith('Faculty') else [0.0, 1.0, 0.05 * i]
        for i, d in enumerate(documents)
    ])


def _record(backend):
    ProcessingMetric.objects.create(
        metric_name=CLUSTERING_RUN_METRIC, metric_value=6, unit='documents', meta={'backend': backend})


@override_settings(
    AI_CLUSTER_USE_EMBEDDINGS=True,
    AI_CLUSTER_HYBRID_METADATA=True,
    AI_CLUSTER_EMBEDDING_MIN_FREE_MB=1536,
)
class BadgeAfterARunTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('badge_admin', password='x')
        cls.admin.profile.role = 'admin'
        cls.admin.profile.save()
        area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        area4, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IV', defaults={'area_name': 'Support to Students'})
        faculty = ('faculty qualifications ranks development plan training workshop '
                   'professor instructor teaching load')
        research = ('research publication journal funding grant thesis dissertation '
                    'laboratory experiment methodology')
        for i in range(3):
            for text, area, name in ((faculty, area2, 'Faculty'), (research, area4, 'Research')):
                Document.objects.create(
                    title=f'{name} {i}', file_type='pdf', year=2026, document_type='Report',
                    extracted_text=f'{text} section {i}', qa_area=area.area_code, acc_area=area,
                    uploaded_by=cls.admin,
                )

    def setUp(self):
        self.client.force_login(self.admin)

    def run_with_embeddings(self):
        with mock.patch.object(embedding_service, 'compute_embedding_matrix',
                               side_effect=_fake_embeddings):
            return run_full_ai_pipeline(None)

    def run_short_of_memory(self):
        with mock.patch.object(embedding_service, '_free_memory_mb', return_value=300), \
                mock.patch.object(embedding_service, '_load_model') as load, \
                self.assertLogs('ai_processing.embedding_service', 'WARNING'):
            message = run_full_ai_pipeline(None)
        load.assert_not_called()
        return message

    def result_page(self):
        doc = Document.objects.exclude(cluster_label=None).order_by('pk').first()
        return self.client.get(reverse('ai_processing:detail', args=[doc.pk]))

    def test_a_background_run_short_of_memory_is_shown_as_tfidf(self):
        """The case this fixes: the settings say embeddings, the run used TF-IDF."""
        self.assertIn('hybrid', self.run_short_of_memory())
        page = self.result_page()
        self.assertContains(page, HYBRID_BADGE)
        self.assertNotContains(page, 'Semantic embeddings')

    def test_a_run_with_embeddings_is_shown_as_embeddings(self):
        self.assertIn('embedding', self.run_with_embeddings())
        self.assertContains(self.result_page(), EMBEDDING_BADGE)

    def test_the_latest_run_decides(self):
        self.run_with_embeddings()
        self.run_short_of_memory()
        self.assertContains(self.result_page(), HYBRID_BADGE)
        self.run_with_embeddings()
        self.assertContains(self.result_page(), EMBEDDING_BADGE)

    def test_each_run_records_what_it_clustered_with(self):
        self.run_short_of_memory()
        row = ProcessingMetric.objects.get(metric_name=CLUSTERING_RUN_METRIC)
        self.assertEqual(row.meta['backend'], 'hybrid')
        self.assertEqual(row.metric_value, Document.objects.count())

    def test_a_run_that_cannot_cluster_records_nothing(self):
        """It leaves the clusters as they were, so the badge keeps describing the run that made them."""
        self.run_with_embeddings()
        with mock.patch('ai_processing.tfidf_service.compute_tfidf_keywords',
                        return_value=(None, [], [])):
            self.assertIn('not enough text', run_full_ai_pipeline(None))
        self.assertEqual(ProcessingMetric.objects.filter(metric_name=CLUSTERING_RUN_METRIC).count(), 1)
        self.assertContains(self.result_page(), EMBEDDING_BADGE)

    def test_failing_to_record_it_does_not_fail_the_run(self):
        real_create = ProcessingMetric.objects.create

        def create(**fields):
            if fields.get('metric_name') == CLUSTERING_RUN_METRIC:
                raise RuntimeError('database unavailable')
            return real_create(**fields)

        with mock.patch.object(ProcessingMetric.objects, 'create', side_effect=create), \
                self.assertLogs('documents.ai_pipeline', 'ERROR'):
            message = self.run_with_embeddings()
        self.assertIn('AI processing complete', message)
        self.assertFalse(Document.objects.filter(cluster_label=None).exists())


class BadgeBeforeAnyRunTests(TestCase):
    """With no run recorded yet, the badge describes the settings -- as it always did."""

    @override_settings(AI_CLUSTER_USE_EMBEDDINGS=True)
    def test_embeddings_enabled(self):
        self.assertEqual(get_clustering_engine_info()['mode'], 'embedding')

    @override_settings(AI_CLUSTER_USE_EMBEDDINGS=False, AI_CLUSTER_HYBRID_METADATA=True)
    def test_embeddings_off(self):
        self.assertEqual(get_clustering_engine_info()['mode'], 'hybrid')

    @override_settings(AI_CLUSTER_USE_EMBEDDINGS=False, AI_CLUSTER_HYBRID_METADATA=False)
    def test_embeddings_and_metadata_off(self):
        self.assertEqual(get_clustering_engine_info()['mode'], 'tfidf')

    @override_settings(AI_CLUSTER_USE_EMBEDDINGS=True)
    def test_a_run_started_from_the_page_still_counts(self):
        request = RequestFactory().get('/')
        request.session = {'ai_cluster_backend': 'hybrid'}
        self.assertEqual(get_clustering_engine_info(request)['mode'], 'hybrid')


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=True, AI_CLUSTER_HYBRID_METADATA=True)
class RecordedMethodTests(TestCase):

    def test_the_record_beats_an_older_page_session(self):
        _record('hybrid')
        request = RequestFactory().get('/')
        request.session = {'ai_cluster_backend': 'embedding'}
        self.assertEqual(get_clustering_engine_info(request)['mode'], 'hybrid')

    def test_a_recorded_tfidf_run_is_shown_as_tfidf(self):
        """It used to show as hybrid whenever the hybrid setting was on."""
        _record('tfidf')
        info = get_clustering_engine_info()
        self.assertEqual((info['label'], info['badge_class']), ('TF-IDF keywords', 'badge-unmapped'))

    def test_an_unrecognised_record_is_ignored(self):
        _record('something-else')
        self.assertEqual(get_clustering_engine_info()['mode'], 'embedding')

    def test_the_three_badges_keep_their_look(self):
        """Same labels, colours and icons as before; only which one is shown changed."""
        expected = {
            'embedding': ('Semantic embeddings', 'badge-complete', 'bi-stars'),
            'hybrid': ('Hybrid TF-IDF + metadata', 'badge-suggested', 'bi-layers'),
            'tfidf': ('TF-IDF keywords', 'badge-unmapped', 'bi-fonts'),
        }
        for backend, look in expected.items():
            with self.subTest(backend):
                _record(backend)
                info = get_clustering_engine_info()
                self.assertEqual((info['label'], info['badge_class'], info['icon']), look)

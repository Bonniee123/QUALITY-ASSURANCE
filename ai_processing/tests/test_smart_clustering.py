"""Tests for area-aware smart clustering."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from ai_processing.cluster_features import build_clustering_matrix
from ai_processing.smart_clustering import (
    build_cluster_display_label,
    clustering_input_text,
    group_documents_by_area,
    group_documents_for_clustering,
    run_smart_clustering,
)
from documents.models import Document
from qa_structure.models import AccreditationArea


class SmartClusteringUnitTests(TestCase):
    def test_build_cluster_display_label(self):
        label = build_cluster_display_label(
            'Area II',
            ['faculty', 'development', 'training'],
            ['Report', 'Report', 'Form'],
        )
        self.assertIn('Area II', label)
        self.assertIn('Report', label)
        self.assertIn('faculty', label)
        self.assertIn('eg.', build_cluster_display_label('Area II', [], [], sample_title='Sample Plan'))

    def test_group_documents_for_clustering_splits_doc_type(self):
        area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )
        user = User.objects.create_user('tester', password='test')
        d1 = Document.objects.create(
            title='A', file_type='pdf', year=2026, document_type='Report',
            qa_area='Area II', acc_area=area2, uploaded_by=user,
        )
        d2 = Document.objects.create(
            title='B', file_type='pdf', year=2026, document_type='Form',
            qa_area='Area II', acc_area=area2, uploaded_by=user,
        )
        groups = group_documents_for_clustering([d1, d2])
        self.assertEqual(len(groups), 2)

    def test_group_documents_by_area_uses_acc_area(self):
        area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )
        area4, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IV', defaults={'area_name': 'Support to Students'},
        )
        user = User.objects.create_user('tester2', password='test')
        d1 = Document.objects.create(
            title='A', file_type='pdf', year=2026, document_type='Report',
            qa_area='Area IV - Research', acc_area=area2, uploaded_by=user,
        )
        d2 = Document.objects.create(
            title='B', file_type='pdf', year=2026, document_type='Report',
            qa_area='Area IV - Research', acc_area=area4, uploaded_by=user,
        )
        groups = group_documents_by_area([d1, d2])
        self.assertEqual(len(groups['Area II']), 1)
        self.assertEqual(len(groups['Area IV']), 1)


@override_settings(
    AI_CLUSTER_WITHIN_AREA=True,
    AI_CLUSTER_WITHIN_DOC_TYPE=True,
    AI_CLUSTER_PAIR_SIMILARITY=0.35,
    AI_CLUSTER_HYBRID_METADATA=True,
)
class SmartClusteringIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )
        cls.area4, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IV', defaults={'area_name': 'Support to Students'},
        )
        cls.user = User.objects.create_user('cluster', password='cluster')

    def _make_doc(self, *, title, text, area, dtype='Report'):
        return Document.objects.create(
            title=title,
            file_type='pdf',
            year=2026,
            document_type=dtype,
            extracted_text=text,
            qa_area=area.area_code,
            acc_area=area,
            uploaded_by=self.user,
        )

    def test_different_areas_never_share_cluster(self):
        faculty_text = (
            'faculty qualifications ranks development plan training workshop '
            'professor instructor teaching load'
        )
        research_text = (
            'research publication journal funding grant thesis dissertation '
            'laboratory experiment methodology'
        )
        docs = [
            self._make_doc(title=f'Faculty {i}', text=faculty_text, area=self.area2)
            for i in range(3)
        ] + [
            self._make_doc(title=f'Research {i}', text=research_text, area=self.area4)
            for i in range(3)
        ]
        cluster_texts = [clustering_input_text(d) for d in docs]
        matrix, features, _backend = build_clustering_matrix(docs, cluster_texts)
        result = run_smart_clustering(docs, matrix, features)

        area2_clusters = {result['labels'][i] for i in range(3)}
        area4_clusters = {result['labels'][i] for i in range(3, 6)}
        self.assertTrue(area2_clusters.isdisjoint(area4_clusters))

    def test_different_doc_types_in_same_area_separate_groups(self):
        text = 'faculty development training workshop seminar professional growth'
        report = self._make_doc(title='Faculty Report', text=text, area=self.area2, dtype='Report')
        syllabus = self._make_doc(title='Faculty Syllabus', text=text, area=self.area2, dtype='Syllabus')
        docs = [report, syllabus]
        cluster_texts = [clustering_input_text(d) for d in docs]
        matrix, features, _ = build_clustering_matrix(docs, cluster_texts)
        result = run_smart_clustering(docs, matrix, features)
        self.assertNotEqual(result['labels'][0], result['labels'][1])

    def test_similar_docs_in_same_area_share_cluster(self):
        shared = (
            'curriculum syllabus course outline learning outcomes assessment rubric '
            'instructional materials module weekly plan'
        )
        docs = [
            self._make_doc(
                title=f'Curriculum {i}',
                text=f'{shared} module week {i} topic section',
                area=self.area2,
                dtype='Syllabus',
            )
            for i in range(4)
        ]
        cluster_texts = [clustering_input_text(d) for d in docs]
        matrix, features, _ = build_clustering_matrix(docs, cluster_texts)
        result = run_smart_clustering(docs, matrix, features)
        labels = result['labels']
        self.assertEqual(len(set(labels)), 1)

    def test_cluster_meta_has_descriptive_label(self):
        doc = self._make_doc(
            title='Faculty plan',
            text='faculty development professional growth training seminar',
            area=self.area2,
            dtype='Report',
        )
        cluster_texts = [clustering_input_text(doc)]
        matrix, features, _ = build_clustering_matrix([doc], cluster_texts)
        result = run_smart_clustering([doc], matrix, features)
        meta = result['cluster_meta'][result['labels'][0]]
        self.assertIn('Area II', meta['display_label'])

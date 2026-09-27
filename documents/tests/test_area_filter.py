"""Tests for document area display and repository area filtering."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserProfile
from documents.area_utils import build_area_filter_q, document_area_code
from documents.models import Document
from qa_structure.models import AccreditationArea
from search.search_service import search_documents


class AreaFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )
        cls.area4, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IV', defaults={'area_name': 'Support to Students'},
        )
        cls.qa = User.objects.create_user('qahead', password='qahead123')
        UserProfile.objects.get_or_create(user=cls.qa, defaults={'role': 'qa_staff'})

        cls.mismatch_doc = Document.objects.create(
            title='Research paper in Area II batch',
            file_type='pdf',
            year=2026,
            document_type='Research',
            qa_area='Area IV - Research',
            acc_area=cls.area2,
            uploaded_by=cls.qa,
        )
        cls.research_only_qa = Document.objects.create(
            title='Legacy research doc',
            file_type='pdf',
            year=2026,
            document_type='Research',
            qa_area='Area IV - Research',
            uploaded_by=cls.qa,
        )
        cls.area2_doc = Document.objects.create(
            title='Faculty report',
            file_type='pdf',
            year=2026,
            document_type='Report',
            qa_area='Area II',
            acc_area=cls.area2,
            uploaded_by=cls.qa,
        )

    def test_document_area_code_prefers_acc_area(self):
        self.assertEqual(document_area_code(self.mismatch_doc), 'Area II')

    def test_area_filter_research_excludes_acc_area_mismatch(self):
        qs = search_documents('', {'area_codes': ['Area IV - Research']})
        ids = set(qs.values_list('pk', flat=True))
        self.assertIn(self.research_only_qa.pk, ids)
        self.assertNotIn(self.mismatch_doc.pk, ids)

    def test_area_filter_area_ii_includes_mismatch_via_acc_area(self):
        qs = search_documents('', {'area_codes': ['Area II']})
        ids = set(qs.values_list('pk', flat=True))
        self.assertIn(self.mismatch_doc.pk, ids)
        self.assertIn(self.area2_doc.pk, ids)
        self.assertNotIn(self.research_only_qa.pk, ids)

    def test_build_area_filter_q_respects_null_acc_area(self):
        from documents.models import Document
        qs = Document.objects.filter(build_area_filter_q(['Area IV - Research']))
        ids = set(qs.values_list('pk', flat=True))
        self.assertEqual(ids, {self.research_only_qa.pk})

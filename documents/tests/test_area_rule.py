"""
One answer to "which area is this document in" (S-AR-02).

A document can carry a linked area (acc_area) and an area code as text
(qa_area) that disagree. The Repository and Faculty access use the linked area;
Area Submissions matched either field, so such a document was counted in two
areas at once.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class AreaSubmissionsRuleTests(TestCase):

    def test_a_document_is_counted_in_its_linked_area_only(self):
        area2, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        area3, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        Document.objects.create(title='Conflicting fields', file='uploaded_documents/c.pdf', file_type='pdf',
                                year=2026, document_type='Report', acc_area=area2, qa_area='Area III')
        Document.objects.create(title='Text code only', file='uploaded_documents/t.pdf', file_type='pdf',
                                year=2026, document_type='Report', qa_area='Area III')
        head = User.objects.create_user('area_head', password='pass12345')
        head.profile.role = 'qa_staff'
        head.profile.save()
        self.client.force_login(head)

        areas = {a['obj'].area_code: a['file_count']
                 for a in self.client.get(reverse('documents:area_submissions')).context['areas']}
        self.assertEqual((areas['Area II'], areas['Area III']), (1, 1))

        detail = self.client.get(reverse('documents:area_submissions') + '?area=Area%20III').content.decode()
        self.assertIn('Text code only', detail)
        self.assertNotIn('Conflicting fields', detail)

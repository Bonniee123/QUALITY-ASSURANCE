"""
Who can delete, and who can take it back.

A single delete is confirmed in a dialog and is then final; a bulk delete can
be undone for a few seconds. These tests pin down the pairing that matters:
every role that can bulk delete a document can undo that delete, nobody can
undo a delete that was not theirs, and Faculty can only ever touch their own
uploads -- whatever the page sent.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class DeleteUndoByRoleTests(TestCase):

    def setUp(self):
        self.area = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )[0]

        def user(name, role):
            account = User.objects.create_user(name, f'{name}@test.com', 'pass12345')
            account.profile.role = role
            account.profile.save()
            return account

        self.admin = user('undo_admin', 'admin')
        self.qa_head = user('undo_qa', 'qa_staff')
        self.faculty = user('undo_faculty', 'faculty')
        self.faculty.profile.assigned_areas.set([self.area])
        self.other_faculty = user('undo_faculty_2', 'faculty')
        self.other_faculty.profile.assigned_areas.set([self.area])

    def document(self, title, owner):
        return Document.objects.create(
            title=title, file=f'uploaded_documents/2026/09/{title}.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area II', acc_area=self.area,
            uploaded_by=owner,
        )

    def bulk_delete(self, *docs):
        return self.client.post(reverse('documents:bulk_delete'), {'document_ids': [d.pk for d in docs]}, **AJAX)

    def undo(self, batch_id):
        return self.client.post(reverse('documents:deletion_undo', args=[batch_id]), {}, **AJAX)

    def assert_delete_and_undo_work(self, account, owner=None):
        doc = self.document(f'doc_for_{account.username}', owner or account)
        self.client.force_login(account)

        response = self.bulk_delete(doc)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Document.objects.live().filter(pk=doc.pk).exists(),
                         f'{account.profile.role} could not delete')
        self.assertTrue(Document.objects.deleted().filter(pk=doc.pk, purged_at__isnull=True).exists(),
                        f'{account.profile.role} deleted the row outright instead of stamping it')

        response = self.undo(response.json()['batch']['id'])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(Document.objects.live().filter(pk=doc.pk).exists(),
                        f'{account.profile.role} could delete but not undo')
        self.assertIsNone(Document.objects.get(pk=doc.pk).deleted_at)

    def test_admin_can_delete_and_undo(self):
        self.assert_delete_and_undo_work(self.admin, owner=self.faculty)

    def test_qa_head_can_delete_and_undo(self):
        self.assert_delete_and_undo_work(self.qa_head, owner=self.faculty)

    def test_faculty_can_delete_and_undo_their_own_upload(self):
        self.assert_delete_and_undo_work(self.faculty)

    def test_faculty_cannot_delete_somebody_elses_upload(self):
        doc = self.document('not_mine', self.other_faculty)
        self.client.force_login(self.faculty)
        self.client.post(reverse('documents:delete', args=[doc.pk]), {})
        self.assertEqual(self.bulk_delete(doc).status_code, 403)
        self.assertTrue(Document.objects.live().filter(pk=doc.pk).exists())

    def test_a_mixed_selection_deletes_only_what_is_theirs(self):
        mine = self.document('mine', self.faculty)
        theirs = self.document('theirs', self.other_faculty)
        self.client.force_login(self.faculty)
        body = self.bulk_delete(mine, theirs).json()
        self.assertEqual((body['deleted'], body['refused']), (1, 1))
        self.assertFalse(Document.objects.live().filter(pk=mine.pk).exists())
        self.assertTrue(Document.objects.live().filter(pk=theirs.pk).exists())

    def test_nobody_can_undo_somebody_elses_delete(self):
        """Undo belongs to the person who deleted, even for another staff account."""
        doc = self.document('deleted_by_admin', self.faculty)
        self.client.force_login(self.admin)
        batch_id = self.bulk_delete(doc).json()['batch']['id']

        for account in (self.faculty, self.qa_head):
            with self.subTest(role=account.profile.role):
                self.client.force_login(account)
                self.assertEqual(self.undo(batch_id).status_code, 404)
                self.assertTrue(Document.objects.deleted().filter(pk=doc.pk).exists(),
                                'someone restored a delete that was not theirs')

    def test_every_role_is_served_the_undo_queue(self):
        """Every role that can bulk delete gets the place undo offers appear in."""
        for account in (self.admin, self.qa_head, self.faculty):
            with self.subTest(role=account.profile.role):
                self.client.force_login(account)
                page = self.client.get(reverse('documents:repository'))
                self.assertContains(page, 'data-pending-deletions-url')
                self.assertNotContains(page, 'bulk-restore')

    def test_faculty_get_checkboxes_only_on_their_own_uploads(self):
        mine = self.document('selectable', self.faculty)
        theirs = self.document('not_selectable', self.other_faculty)
        self.client.force_login(self.faculty)
        page = self.client.get(reverse('documents:repository')).content.decode()
        self.assertIn(f'value="{mine.pk}"', page)
        self.assertNotIn(f'name="document_ids" value="{theirs.pk}"', page)

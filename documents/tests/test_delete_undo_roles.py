"""
Who can delete, and who can take it back (S-DEL-01).

Deletion used to mean two different things depending on which button was
pressed: the bulk Delete stamped a row and offered ten seconds of undo, while
the row menu's Delete removed the row and erased the file. A document was lost
that way. Both are reversible now, and these tests pin down the pairing that
matters: every role that can delete a document can also restore it, and no role
can restore a document it was never allowed to delete.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


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

    def delete(self, doc):
        return self.client.post(reverse('documents:delete', args=[doc.pk]), {})

    def restore(self, doc):
        return self.client.post(reverse('documents:bulk_restore'), {'document_ids': [doc.pk]})

    def assert_delete_and_undo_work(self, account, owner=None):
        doc = self.document(f'doc_for_{account.username}', owner or account)
        self.client.force_login(account)

        self.delete(doc)
        self.assertFalse(Document.objects.live().filter(pk=doc.pk).exists(),
                         f'{account.profile.role} could not delete')
        self.assertTrue(Document.objects.deleted().filter(pk=doc.pk).exists(),
                        f'{account.profile.role} deleted the row outright instead of stamping it')
        self.assertEqual(self.client.session.get('pending_undo'), {'ids': [doc.pk], 'count': 1})

        self.restore(doc)
        self.assertTrue(Document.objects.live().filter(pk=doc.pk).exists(),
                        f'{account.profile.role} could delete but not undo')
        self.assertIsNone(Document.objects.get(pk=doc.pk).deleted_at)

    def test_admin_can_delete_and_undo(self):
        self.assert_delete_and_undo_work(self.admin)

    def test_qa_head_can_delete_and_undo(self):
        self.assert_delete_and_undo_work(self.qa_head)

    def test_faculty_can_delete_and_undo_their_own_upload(self):
        self.assert_delete_and_undo_work(self.faculty)

    def test_faculty_cannot_delete_somebody_elses_upload(self):
        doc = self.document('not_mine', self.other_faculty)
        self.client.force_login(self.faculty)
        self.delete(doc)
        self.assertTrue(Document.objects.live().filter(pk=doc.pk).exists())

    def test_faculty_cannot_restore_somebody_elses_deleted_upload(self):
        """The restore endpoint is reachable by Faculty, so it checks each document."""
        doc = self.document('deleted_by_admin', self.other_faculty)
        self.client.force_login(self.admin)
        self.delete(doc)

        self.client.force_login(self.faculty)
        self.restore(doc)
        self.assertTrue(Document.objects.deleted().filter(pk=doc.pk).exists(),
                        'Faculty restored a document they were never allowed to delete')

    def test_every_role_is_served_the_undo_strip(self):
        """
        The strip sits outside the bulk bar's QA-staff block.

        It used to be inside it, which meant a Faculty member deleting their own
        upload got no way back -- the one role most likely to need it.
        """
        for account in (self.admin, self.qa_head, self.faculty):
            with self.subTest(role=account.profile.role):
                self.client.force_login(account)
                page = self.client.get(reverse('documents:repository'))
                self.assertContains(page, 'id="repoUndoBar"')
                self.assertContains(page, 'data-restore-url')

    def test_only_qa_staff_and_admin_reach_the_bulk_delete(self):
        """Faculty delete one document at a time; the bulk bar is not theirs."""
        doc = self.document('bulk_target', self.faculty)
        self.client.force_login(self.faculty)
        self.client.post(reverse('documents:bulk_delete'), {'document_ids': [doc.pk]})
        self.assertTrue(Document.objects.live().filter(pk=doc.pk).exists())

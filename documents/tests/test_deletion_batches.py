"""
Deleting with independent undo windows, and never losing who did what.

Each bulk delete is a batch with its own ten seconds. Deleting ten documents
and then five more makes two batches: undoing one leaves the other, and the
other still expires on its own clock. When a window closes the files are
removed and the deletion is permanent, but the documents' records and their
history (uploaded -> deleted -> restored -> permanently deleted) remain for
administrators. The server decides, per document and at the moment of the
request, who may delete and who may undo.
"""
import os
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documents.deletion import finalize_batch, finalize_expired_batches
from documents.models import ActivityLog, DeletionBatch, Document
from notifications.models import Notification
from qa_structure.models import AccreditationArea

MEDIA = tempfile.mkdtemp(prefix='qa-del-tests-')


def make_user(name, role, areas=()):
    user = User.objects.create_user(name, f'{name}@test.local', 'pass12345', first_name=name.title())
    user.profile.role = role
    user.profile.save()
    if areas:
        user.profile.assigned_areas.set(areas)
    return user


@override_settings(MEDIA_ROOT=MEDIA, DELETE_UNDO_SECONDS=10, DELETE_UNDO_GRACE_SECONDS=3)
class DeletionBatchTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.area = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})[0]
        self.other_area = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})[0]
        self.admin = make_user('del_admin', 'admin')
        self.qa_head = make_user('del_qa', 'qa_staff')
        self.faculty_a = make_user('del_fac_a', 'faculty', [self.area])
        self.faculty_b = make_user('del_fac_b', 'faculty', [self.area])

    def doc(self, owner, n, area=None):
        area = area or self.area
        return Document.objects.create(
            title=f'{owner.username} doc {n}', file=SimpleUploadedFile(f'{owner.username}_{n}.pdf', b'%PDF-1.4 test'),
            file_type='pdf', year=2026, document_type='Report', qa_area=area.area_code, acc_area=area,
            uploaded_by=owner,
        )

    def bulk_delete(self, docs, as_user):
        self.client.force_login(as_user)
        return self.client.post(reverse('documents:bulk_delete'), {'document_ids': [d.pk for d in docs]},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def undo(self, batch_id, as_user):
        self.client.force_login(as_user)
        return self.client.post(reverse('documents:deletion_undo', args=[batch_id]),
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def expire(self, batch_id):
        DeletionBatch.objects.filter(pk=batch_id).update(expires_at=timezone.now() - timedelta(seconds=30))

    def live_ids(self):
        return set(Document.objects.live().values_list('pk', flat=True))

    # --------------------------------------------------- the main scenario

    def test_two_overlapping_bulk_deletes_keep_their_own_undo(self):
        ten = [self.doc(self.faculty_a, n) for n in range(10)]
        five = [self.doc(self.faculty_a, n) for n in range(10, 15)]

        first = self.bulk_delete(ten, self.faculty_a).json()
        second = self.bulk_delete(five, self.faculty_a).json()
        self.assertEqual((first['deleted'], second['deleted']), (10, 5))
        self.assertNotEqual(first['batch']['id'], second['batch']['id'])
        self.assertEqual(first['batch']['expires_at_ms'] <= second['batch']['expires_at_ms'], True)

        pending = self.client.get(reverse('documents:deletions_pending')).json()['batches']
        self.assertEqual(sum(b['count'] for b in pending), 15, 'both batches offered: 15 to undo')

        # Undo only the second batch: the first ten stay deleted and pending.
        response = self.undo(second['batch']['id'], self.faculty_a).json()
        self.assertEqual(response['restored'], 5)
        self.assertEqual(self.live_ids(), {d.pk for d in five})
        self.assertEqual(DeletionBatch.objects.get(pk=first['batch']['id']).status, DeletionBatch.STATUS_PENDING)

        # The first batch expires on its own clock and becomes permanent.
        self.expire(first['batch']['id'])
        self.assertEqual(finalize_expired_batches(), 1)
        for doc in ten:
            doc.refresh_from_db()
            self.assertIsNotNone(doc.purged_at)
            self.assertFalse(doc.file)
            self.assertFalse(os.path.exists(os.path.join(MEDIA, 'uploaded_documents', doc.original_filename)))
        for doc in five:
            doc.refresh_from_db()
            self.assertTrue(os.path.exists(doc.file.path), 'a restored document keeps its file')

        # And it can no longer be undone.
        self.assertEqual(self.undo(first['batch']['id'], self.faculty_a).status_code, 410)

    def test_undo_after_the_window_is_refused_even_before_finalizing(self):
        docs = [self.doc(self.faculty_a, n) for n in range(3)]
        batch = self.bulk_delete(docs, self.faculty_a).json()['batch']
        self.expire(batch['id'])
        response = self.undo(batch['id'], self.faculty_a)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()['code'], 'expired')
        self.assertFalse(self.live_ids() & {d.pk for d in docs})

    def test_undo_and_expiry_cannot_both_win(self):
        docs = [self.doc(self.faculty_a, n) for n in range(2)]
        batch_id = self.bulk_delete(docs, self.faculty_a).json()['batch']['id']
        self.assertEqual(self.undo(batch_id, self.faculty_a).json()['restored'], 2)
        self.assertFalse(finalize_batch(DeletionBatch.objects.get(pk=batch_id)))
        self.assertEqual(self.live_ids(), {d.pk for d in docs})

    # ------------------------------------------------------- permissions

    def test_faculty_bulk_delete_takes_only_their_own_uploads(self):
        mine = [self.doc(self.faculty_a, n) for n in range(2)]
        theirs = self.doc(self.faculty_b, 1)
        response = self.bulk_delete(mine + [theirs], self.faculty_a).json()
        self.assertEqual(response['deleted'], 2)
        self.assertEqual(response['refused'], 1)
        self.assertIn(theirs.pk, self.live_ids())

    def test_faculty_cannot_delete_by_sending_someone_elses_ids(self):
        theirs = [self.doc(self.faculty_b, n) for n in range(2)]
        response = self.bulk_delete(theirs, self.faculty_a)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.live_ids(), {d.pk for d in theirs})

    def test_only_the_person_who_deleted_can_undo(self):
        docs = [self.doc(self.faculty_a, n) for n in range(2)]
        batch_id = self.bulk_delete(docs, self.faculty_a).json()['batch']['id']
        for other in (self.faculty_b, self.qa_head):
            self.assertEqual(self.undo(batch_id, other).status_code, 404, other.username)
        self.assertFalse(self.live_ids() & {d.pk for d in docs})

    def test_undo_restores_only_what_the_person_may_still_manage(self):
        docs = [self.doc(self.faculty_a, n) for n in range(3)]
        batch_id = self.bulk_delete(docs, self.faculty_a).json()['batch']['id']
        # The area is taken away before the undo.
        self.faculty_a.profile.assigned_areas.set([self.other_area])
        response = self.undo(batch_id, self.faculty_a).json()
        self.assertEqual((response['restored'], response['refused']), (0, 3))
        self.assertFalse(self.live_ids() & {d.pk for d in docs})
        for doc in docs:
            doc.refresh_from_db()
            self.assertIsNotNone(doc.purged_at, 'refused documents are made permanent, not left hanging')

    def test_qa_head_and_admin_bulk_delete_anyones_documents(self):
        docs = [self.doc(self.faculty_a, 1), self.doc(self.faculty_b, 2)]
        self.assertEqual(self.bulk_delete(docs, self.qa_head).json()['deleted'], 2)

    # ------------------------------------------------------ single delete

    def test_single_delete_is_confirmed_then_permanent_with_no_undo(self):
        doc = self.doc(self.faculty_a, 1)
        path = doc.file.path
        self.client.force_login(self.faculty_a)
        confirm = self.client.get(reverse('documents:delete', args=[doc.pk]))
        self.assertEqual(confirm.status_code, 200, 'GET shows the confirmation, deletes nothing')
        self.assertIn(doc.pk, self.live_ids())

        self.client.post(reverse('documents:delete', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertIsNotNone(doc.deleted_at)
        self.assertIsNotNone(doc.purged_at)
        self.assertFalse(os.path.exists(path))
        batch = DeletionBatch.objects.get(pk=doc.deletion_batch_id)
        self.assertEqual((batch.kind, batch.status), (DeletionBatch.KIND_SINGLE, DeletionBatch.STATUS_FINALIZED))
        self.assertEqual(self.client.get(reverse('documents:deletions_pending')).json()['batches'], [])

    def test_a_deleted_document_cannot_be_opened_or_downloaded(self):
        doc = self.doc(self.faculty_a, 1)
        self.bulk_delete([doc], self.faculty_a)
        self.client.force_login(self.admin)
        for name in ('detail', 'download', 'view', 'serve', 'preview', 'edit'):
            self.assertEqual(self.client.get(reverse(f'documents:{name}', args=[doc.pk])).status_code, 404, name)

    # -------------------------------------------------- history and notices

    def test_history_reads_uploaded_deleted_restored_deleted_permanently(self):
        doc = self.doc(self.faculty_a, 1)
        batch_id = self.bulk_delete([doc], self.qa_head).json()['batch']['id']
        self.undo(batch_id, self.qa_head)
        second = self.bulk_delete([doc], self.faculty_a).json()['batch']['id']
        self.expire(second)
        finalize_expired_batches()

        history = list(ActivityLog.objects.filter(document=doc).order_by('id')
                       .values_list('action', 'actor_name'))
        self.assertEqual([a for a, _ in history],
                         ['upload_document', 'bulk_delete_document', 'restore_document',
                          'bulk_delete_document', 'purge_document'])
        self.assertEqual(history[0][1], 'Del_Fac_A', 'uploader recorded')
        self.assertEqual(history[1][1], 'Del_Qa', 'first deleter recorded')
        self.assertEqual(history[3][1], 'Del_Fac_A', 'second deleter recorded')
        doc.refresh_from_db()
        self.assertEqual(doc.deleted_by, self.faculty_a)
        self.assertEqual(doc.uploaded_by, self.faculty_a, 'who uploaded it survives deletion')

    def test_deletion_notifies_staff_once_when_permanent_and_not_for_an_undo(self):
        undone = [self.doc(self.faculty_a, n) for n in range(2)]
        kept = [self.doc(self.faculty_a, n) for n in range(2, 4)]
        first = self.bulk_delete(undone, self.faculty_a).json()['batch']['id']
        self.undo(first, self.faculty_a)
        second = self.bulk_delete(kept, self.faculty_a).json()['batch']['id']
        self.expire(second)
        finalize_expired_batches()
        finalize_batch(DeletionBatch.objects.get(pk=second))   # processed twice

        for staff in (self.admin, self.qa_head):
            notes = list(Notification.objects.filter(user=staff, category='deletion').values_list('message', flat=True))
            self.assertEqual(notes, ['Documents Deleted — Del_Fac_A deleted 2 documents'], staff.username)
            # Document History is the Administrator's; a QA Head is linked to
            # the Repository, a page they can open.
            link = Notification.objects.get(user=staff, category='deletion').link
            expected = reverse('accounts:document_history') if staff.profile.role == 'admin' \
                else reverse('documents:repository')
            self.assertEqual(link, expected, staff.username)
        self.assertFalse(Notification.objects.filter(user=self.faculty_a, category='deletion').exists(),
                         'nobody is notified of their own deletion')

    def test_upload_history_survives_permanent_deletion_for_the_document_history_page(self):
        doc = self.doc(self.faculty_a, 1)
        self.client.force_login(self.faculty_a)
        self.client.post(reverse('documents:delete', args=[doc.pk]))
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:document_history')).content.decode()
        self.assertIn(doc.title, page)
        self.assertIn('Del_Fac_A', page)
        self.assertIn('Permanently deleted', page)

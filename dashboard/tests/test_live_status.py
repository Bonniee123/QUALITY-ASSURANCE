"""
The live poll (/dashboard/live/) and what hangs off it.

Every open page polls it, so it has to stay small, tell people only about the
documents they can see, change its fingerprint when the documents change, and
never keep an idle session alive.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from documents.models import DeletionBatch, Document
from notifications.models import Notification
from qa_structure.models import AccreditationArea

PASSWORD = 'pass12345'


class LiveStatusTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area2 = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})[0]
        cls.area3 = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})[0]

        def user(name, role, areas=()):
            account = User.objects.create_user(name, f'{name}@test.com', PASSWORD)
            account.profile.role = role
            account.profile.save()
            if areas:
                account.profile.assigned_areas.set(areas)
            return account

        cls.admin = user('live_admin', 'admin')
        cls.faculty = user('live_fac', 'faculty', [cls.area2])

    def document(self, title, area, owner=None):
        return Document.objects.create(
            title=title, file=f'uploaded_documents/2026/10/{title}.pdf', file_type='pdf', year=2026,
            document_type='Report', qa_area=area.area_code, acc_area=area, uploaded_by=owner or self.admin,
        )

    def live(self, user, **headers):
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard:live'), **headers)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_it_carries_the_counts_and_a_document_fingerprint(self):
        Notification.objects.create(user=self.admin, message='hello', category='upload')
        body = self.live(self.admin)
        self.assertEqual(body['unread_notifications'], 1)
        self.assertIn('unread_messages', body)
        self.assertIn('stamp', body['documents'])

    def test_the_fingerprint_changes_on_upload_and_on_delete(self):
        first = self.live(self.admin)['documents']['stamp']
        doc = self.document('live_one', self.area2)
        second = self.live(self.admin)['documents']['stamp']
        self.assertNotEqual(first, second)
        Document.objects.filter(pk=doc.pk).update(deleted_at=timezone.now())
        self.assertNotEqual(second, self.live(self.admin)['documents']['stamp'])

    def test_faculty_only_count_their_own_areas(self):
        self.document('in_area_2', self.area2)
        self.document('in_area_3', self.area3)
        self.assertEqual(self.live(self.faculty)['documents']['count'], 1)
        self.assertEqual(self.live(self.admin)['documents']['count'], 2)

    def test_a_poll_finalizes_expired_deletions(self):
        doc = self.document('expired', self.area2)
        now = timezone.now()
        batch = DeletionBatch.objects.create(
            user=self.admin, user_name='live_admin', kind=DeletionBatch.KIND_BULK,
            document_ids=[doc.pk], document_count=1, expires_at=now - timedelta(minutes=1),
        )
        Document.objects.filter(pk=doc.pk).update(deleted_at=now, deleted_by=self.admin, deletion_batch=batch)
        self.live(self.faculty)
        batch.refresh_from_db()
        self.assertEqual(batch.status, DeletionBatch.STATUS_FINALIZED)
        self.assertIsNotNone(Document.objects.get(pk=doc.pk).purged_at)

    def test_a_passive_poll_does_not_count_as_activity(self):
        """The same rule as every other poller: an unattended screen still times out."""
        self.client.force_login(self.admin)
        earlier = timezone.now().timestamp() - 30
        session = self.client.session
        session['_auth_last_activity'] = earlier
        session.save()
        self.assertEqual(self.client.get(reverse('dashboard:live'), HTTP_X_QA_PASSIVE='1').status_code, 200)
        self.assertEqual(self.client.session.get('_auth_last_activity'), earlier)


class BellRefreshTests(TestCase):

    def test_the_dropdown_lists_the_newest_notification(self):
        user = User.objects.create_user('bell_admin', 'b@test.com', PASSWORD)
        user.profile.role = 'admin'
        user.profile.save()
        Notification.objects.create(user=user, message='Documents Deleted — X deleted 3 documents', category='deletion')
        self.client.force_login(user)
        response = self.client.get(reverse('notifications:dropdown'))
        self.assertContains(response, 'Documents Deleted')
        self.assertContains(response, 'bi-trash3')
        self.assertContains(response, 'just now')
        self.assertNotContains(response, '<html')


class DocumentHistoryAccessTests(TestCase):

    def test_admin_and_qa_head_may_open_it_faculty_may_not(self):
        for role, status in (('admin', 200), ('qa_staff', 200), ('faculty', 403)):
            with self.subTest(role=role):
                user = User.objects.create_user(f'hist_{role}', f'{role}@test.com', PASSWORD)
                user.profile.role = role
                user.profile.save()
                self.client.force_login(user)
                response = self.client.get(reverse('accounts:document_history'))
                self.assertEqual(response.status_code if response.status_code != 302 else 403, status)


class StaleNotificationTests(TestCase):
    """A notification never leads to a page that no longer exists."""

    def test_a_link_to_a_deleted_document_opens_its_history_instead(self):
        admin = User.objects.create_user('stale_admin', 's@test.com', PASSWORD)
        admin.profile.role = 'admin'
        admin.profile.save()
        doc = Document.objects.create(title='Gone Report', file='uploaded_documents/x.pdf', file_type='pdf',
                                      year=2026, document_type='Report', uploaded_by=admin)
        note = Notification.objects.create(user=admin, message='possible duplicate', category='duplicate',
                                           link=f'/documents/{doc.pk}/')
        Document.objects.filter(pk=doc.pk).update(deleted_at=timezone.now())
        self.client.force_login(admin)
        response = self.client.get(reverse('notifications:open', args=[note.pk]))
        self.assertRedirects(response, reverse('accounts:document_history') + '?q=Gone%20Report',
                             fetch_redirect_response=False)

    def test_a_link_to_a_live_document_is_followed(self):
        admin = User.objects.create_user('live_link_admin', 'l@test.com', PASSWORD)
        admin.profile.role = 'admin'
        admin.profile.save()
        doc = Document.objects.create(title='Here Report', file='uploaded_documents/y.pdf', file_type='pdf',
                                      year=2026, document_type='Report', uploaded_by=admin)
        note = Notification.objects.create(user=admin, message='x', category='duplicate', link=f'/documents/{doc.pk}/')
        self.client.force_login(admin)
        response = self.client.get(reverse('notifications:open', args=[note.pk]))
        self.assertRedirects(response, f'/documents/{doc.pk}/', fetch_redirect_response=False)

"""Tests for user-facing notification copy."""
from django.contrib.auth.models import User
from django.test import TestCase

from documents.models import BackgroundJob
from notifications.user_messages import bulk_upload_notification_message


class BulkUploadNotificationMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('notif_user', 'n@test.com', 'pass12345')

    def _job(self, **payload):
        return BackgroundJob.objects.create(
            job_type='bulk_upload_process',
            payload=payload,
            created_by=self.user,
        )

    def test_single_success_is_plain_language(self):
        job = self._job(total_count=1, processed_count=1, errors=[])
        msg = bulk_upload_notification_message(job, success=True)
        self.assertIn('uploaded successfully', msg)
        self.assertNotIn('job #', msg.lower())
        self.assertNotIn('ai processing', msg.lower())

    def test_multiple_success(self):
        job = self._job(total_count=3, processed_count=3, errors=[])
        msg = bulk_upload_notification_message(job, success=True)
        self.assertIn('3 documents', msg)

    def test_partial_failure(self):
        job = self._job(total_count=2, processed_count=1, errors=['bad.pdf: error'])
        msg = bulk_upload_notification_message(job, success=True)
        self.assertIn('1 document', msg)
        self.assertIn('1 file', msg)

    def test_failure_message(self):
        job = self._job(total_count=1, processed_count=0, errors=[])
        msg = bulk_upload_notification_message(job, success=False)
        self.assertIn('could not be completed', msg)

    def test_duplicate_message_is_plain(self):
        from notifications.user_messages import duplicate_detected_message, version_supersede_message

        dup = duplicate_detected_message('Annual Report 2026', 2)
        self.assertNotIn('possible duplicate detected', dup.lower())
        self.assertIn('similar', dup.lower())

        ver = version_supersede_message('New file', 'Old file')
        self.assertIn('newer version', ver.lower())

    def test_legacy_notification_display_strips_job_ids(self):
        from notifications.user_messages import display_notification_message

        raw = '4/4 document(s) processed. AI processing completed (job #45)'
        clean = display_notification_message(raw)
        self.assertNotIn('job #', clean.lower())
        self.assertIn('processed', clean.lower())

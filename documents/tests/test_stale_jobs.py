"""
Jobs that stop responding (S-JOB-02).

A background job runs on a thread inside the web server. When that thread dies
without raising -- a restart, or a native crash inside an embedding or OCR
library, which no `except` can catch -- the row stays 'running' and every
document in the batch stays on "Processing" on a page that will never change.
One upload sat at 2 of 17 files for nearly two hours that way.

`recover_interrupted_jobs` covers the process dying and coming back. These
tests cover the other half: the process is alive, the worker is not.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documents.jobs import sweep_stale_jobs
from documents.models import BackgroundJob, Document


class StaleJobSweepTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('stale_admin', 'sa@test.com', 'pass12345')
        self.user.profile.role = 'admin'
        self.user.profile.save()

    def document(self, title='Half-processed file'):
        return Document.objects.create(
            title=title, file=f'uploaded_documents/2026/09/{title}.pdf', file_type='pdf',
            year=2026, document_type='Report', is_processed=False,
        )

    def job(self, heartbeat_minutes_ago=None, started_minutes_ago=60, doc_ids=(), status='running'):
        payload = {'document_ids': list(doc_ids), 'total_count': len(doc_ids), 'processed_count': 0}
        if heartbeat_minutes_ago is not None:
            payload['heartbeat'] = (
                timezone.now() - timedelta(minutes=heartbeat_minutes_ago)).isoformat()
        job = BackgroundJob.objects.create(
            job_type='bulk_upload_process', payload=payload, created_by=self.user)
        BackgroundJob.objects.filter(pk=job.pk).update(
            status=status, started_at=timezone.now() - timedelta(minutes=started_minutes_ago),
        )
        job.refresh_from_db()
        return job

    def test_a_job_that_stopped_reporting_is_failed(self):
        job = self.job(heartbeat_minutes_ago=45)
        self.assertEqual(sweep_stale_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('Stopped responding', job.error)
        self.assertIsNotNone(job.finished_at)

    def test_its_documents_stop_saying_processing(self):
        doc = self.document()
        self.assertTrue(doc.processing_in_progress)
        self.job(heartbeat_minutes_ago=45, doc_ids=[doc.pk])
        sweep_stale_jobs()
        doc.refresh_from_db()
        self.assertFalse(doc.processing_in_progress)
        self.assertIn('Upload it again', doc.processing_error)

    def test_a_job_still_reporting_progress_is_left_alone(self):
        """
        Slow is not dead.

        A batch of large scanned PDFs can spend many minutes on one file, so
        staleness is measured from the last progress report, never from the
        start. Judging by `started_at` would kill a job that is working.
        """
        job = self.job(heartbeat_minutes_ago=1, started_minutes_ago=600)
        self.assertEqual(sweep_stale_jobs(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')

    def test_a_job_that_never_reported_falls_back_to_when_it_started(self):
        job = self.job(heartbeat_minutes_ago=None, started_minutes_ago=90)
        self.assertEqual(sweep_stale_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_a_young_job_with_no_heartbeat_yet_is_left_alone(self):
        job = self.job(heartbeat_minutes_ago=None, started_minutes_ago=2)
        self.assertEqual(sweep_stale_jobs(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')

    def test_finished_jobs_are_never_touched(self):
        job = self.job(heartbeat_minutes_ago=600, status='completed')
        sweep_stale_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')

    @override_settings(JOB_STALE_MINUTES=0)
    def test_the_check_can_be_switched_off(self):
        job = self.job(heartbeat_minutes_ago=600)
        self.assertEqual(sweep_stale_jobs(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')

    def test_a_completed_document_is_not_given_an_error(self):
        """Only the files that never finished are marked; the rest are done."""
        done = self.document('Finished file')
        Document.objects.filter(pk=done.pk).update(is_processed=True)
        pending = self.document('Unfinished file')
        self.job(heartbeat_minutes_ago=45, doc_ids=[done.pk, pending.pk])
        sweep_stale_jobs()
        done.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(done.processing_error, '')
        self.assertNotEqual(pending.processing_error, '')

    def test_the_repository_page_sweeps(self):
        """Somebody watching the stuck document is who should see it resolve."""
        doc = self.document()
        job = self.job(heartbeat_minutes_ago=45, doc_ids=[doc.pk])
        self.client.force_login(self.user)
        self.client.get(reverse('documents:repository'))
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_the_status_endpoint_sweeps(self):
        job = self.job(heartbeat_minutes_ago=45)
        self.client.force_login(self.user)
        response = self.client.get(reverse('documents:job_status', args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')

"""Tests for background job state handling and crash containment."""
import threading
from unittest import mock

from django.db import connection
from django.test import TestCase

from documents.jobs import _persist_job_state, _run_job_in_thread, run_job
from documents.models import BackgroundJob


class PersistJobStateTests(TestCase):
    def test_writes_fields_to_db_and_instance(self):
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        _persist_job_state(job, status='running', error='')

        self.assertEqual(job.status, 'running')
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')

    def test_does_not_raise_when_row_is_gone(self):
        """
        A worker thread can start before the enqueueing transaction commits, so the
        row may not be visible. save(update_fields=...) raises DatabaseError there;
        bookkeeping must never take the job down.
        """
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        pk = job.pk
        BackgroundJob.objects.filter(pk=pk).delete()

        _persist_job_state(job, status='running')  # must not raise

        self.assertEqual(job.status, 'running')
        self.assertFalse(BackgroundJob.objects.filter(pk=pk).exists())


class RunJobFailureTests(TestCase):
    def test_unknown_job_type_is_recorded_as_failed(self):
        job = BackgroundJob.objects.create(job_type='not_a_real_job')
        self.assertFalse(run_job(job))

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('not_a_real_job', job.error)
        self.assertIsNotNone(job.finished_at)

    def test_pipeline_exception_is_recorded_as_failed(self):
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        with mock.patch(
            'documents.jobs.run_full_ai_pipeline', side_effect=RuntimeError('boom')
        ):
            self.assertFalse(run_job(job))

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error, 'boom')


class ThreadCrashContainmentTests(TestCase):
    def test_crash_in_worker_leaves_job_failed_not_pending(self):
        """
        Previously an exception escaping run_job died silently inside the daemon
        thread, stranding the job at 'pending' with nothing shown in the UI.
        """
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        with mock.patch('documents.jobs.run_job', side_effect=RuntimeError('thread boom')):
            _run_job_in_thread(job)  # must not propagate

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('crashed', job.error.lower())
        self.assertIsNotNone(job.finished_at)

    def test_successful_run_is_left_alone(self):
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        with mock.patch('documents.jobs.run_job', return_value=True) as runner:
            _run_job_in_thread(job)
        runner.assert_called_once_with(job)

        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')  # untouched by the wrapper

    def test_main_thread_connection_is_not_closed(self):
        """
        The wrapper closes the worker's own database connection, but must never close
        the caller's. Closing it on the main thread aborts the surrounding
        transaction, which on MySQL surfaces as TransactionManagementError on the
        caller's very next query.
        """
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        with mock.patch('documents.jobs.run_job', side_effect=RuntimeError('boom')):
            _run_job_in_thread(job)

        # Any query here proves the caller's connection and transaction survived.
        self.assertEqual(BackgroundJob.objects.filter(pk=job.pk).count(), 1)

    def test_worker_thread_closes_its_own_connection(self):
        """A real worker thread must release its connection so it does not leak."""
        job = BackgroundJob.objects.create(job_type='full_ai_pipeline')
        closed = []

        def fake_close():
            closed.append(threading.current_thread().name)

        def target():
            with mock.patch('documents.jobs.run_job', return_value=True), \
                    mock.patch.object(connection, 'close', fake_close):
                _run_job_in_thread(job)

        worker = threading.Thread(target=target)
        worker.start()
        worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(closed), 1, 'worker thread should close its connection exactly once')

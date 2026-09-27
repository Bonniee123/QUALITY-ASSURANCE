"""
Tests for upload batch progress and the duplicate verdict.

The two bugs these cover both showed up as the same symptom -- a Duplicate
column stuck on "Checking…" and an upload panel that emptied itself -- but had
separate causes, so they are pinned separately.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from documents.models import BackgroundJob, Document
from documents.upload_batches import batch_detail, recent_batches


def make_doc(**kwargs):
    defaults = dict(
        title='Doc', file='uploaded_documents/2026/01/x.pdf', file_type='pdf',
        year=2026, document_type='Report',
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


class DuplicateVerdictTests(TestCase):
    """
    A document that is checked and found clean must be recorded as clean.

    `check_all_duplicates` only returns entries for documents that *have* a
    match, and the pipeline used to iterate that map. A clean document was
    therefore never visited and kept the 'pending_check' it was created with,
    which the repository renders as "Checking…" -- forever, on exactly the
    documents with nothing wrong with them.
    """

    def test_clean_document_is_resolved_not_left_pending(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Alpha budget report', extracted_text='budget figures for the alpha programme ' * 20)
        make_doc(title='Beta laboratory manual', extracted_text='laboratory safety procedures beta ' * 20)

        run_full_ai_pipeline(None)

        self.assertFalse(
            Document.objects.filter(duplicate_status='pending_check').exists(),
            'a checked document was left on "Checking…"',
        )

    def test_every_document_gets_a_verdict(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        for i in range(5):
            make_doc(title=f'Report {i}', extracted_text=f'distinct subject matter number {i} ' * 20)
        run_full_ai_pipeline(None)

        statuses = set(Document.objects.values_list('duplicate_status', flat=True))
        self.assertNotIn('pending_check', statuses)
        self.assertTrue(statuses <= {'none', 'possible', 'confirmed_dup'})


class BatchStateTests(TestCase):
    """Per-file state comes from the document, not from the job row."""

    def setUp(self):
        self.user = User.objects.create_user('batch_u', 'b@e.com', 'testpass123')

    def job_for(self, docs, total=None):
        return BackgroundJob.objects.create(
            job_type='bulk_upload_process',
            created_by=self.user,
            status='completed',
            payload={'document_ids': [d.pk for d in docs],
                     'total_count': total if total is not None else len(docs)},
        )

    def test_completed_document_reads_as_completed(self):
        doc = make_doc(is_processed=True, duplicate_status='none', cluster_label=1)
        batch = batch_detail(self.job_for([doc]))
        self.assertEqual(batch['files'][0]['state'], 'completed')
        self.assertTrue(batch['finished'])
        self.assertEqual(batch['percent'], 100)

    def test_pending_check_still_reads_as_processing(self):
        # The whole point: the job says "completed" but the document has not
        # been through duplicate detection, so the batch is not finished.
        doc = make_doc(is_processed=True, duplicate_status='pending_check')
        batch = batch_detail(self.job_for([doc]))
        self.assertEqual(batch['files'][0]['state'], 'processing')
        self.assertFalse(batch['finished'])

    def test_duplicate_is_its_own_state_with_a_reason(self):
        doc = make_doc(is_processed=True, duplicate_status='possible',
                       similar_documents=[{'id': 9, 'title': 'Older copy', 'similarity': 0.93}])
        row = batch_detail(self.job_for([doc]))['files'][0]
        self.assertEqual(row['state'], 'duplicate')
        self.assertIn('93%', row['detail'])
        self.assertIn('Older copy', row['detail'])

    def test_failed_document_carries_its_error(self):
        doc = make_doc(is_processed=True, processing_error='Could not read the file.')
        row = batch_detail(self.job_for([doc]))['files'][0]
        self.assertEqual(row['state'], 'failed')
        self.assertIn('Could not read', row['detail'])

    def test_deleted_document_is_removed_not_failed(self):
        doc = make_doc(is_processed=True, duplicate_status='none')
        job = self.job_for([doc])
        doc.delete()
        row = batch_detail(job)['files'][0]
        self.assertEqual(row['state'], 'removed')
        self.assertNotEqual(row['state'], 'failed')

    def test_files_not_yet_saved_are_queued(self):
        doc = make_doc(is_processed=True, duplicate_status='none')
        batch = batch_detail(self.job_for([doc], total=3))
        self.assertEqual([f['state'] for f in batch['files']],
                         ['completed', 'queued', 'queued'])
        self.assertFalse(batch['finished'])

    def test_long_running_document_is_reported_stalled(self):
        doc = make_doc(is_processed=False, duplicate_status='pending_check')
        Document.objects.filter(pk=doc.pk).update(
            uploaded_at=timezone.now() - timezone.timedelta(hours=2))
        batch = batch_detail(self.job_for([Document.objects.get(pk=doc.pk)]))
        self.assertTrue(batch['stalled'])
        self.assertTrue(batch['files'][0]['stalled'])

    def test_counts_add_up(self):
        docs = [
            make_doc(title='a', is_processed=True, duplicate_status='none'),
            make_doc(title='b', is_processed=True, duplicate_status='possible'),
            make_doc(title='c', is_processed=True, processing_error='boom'),
        ]
        batch = batch_detail(self.job_for(docs))
        self.assertEqual(batch['counts']['completed'], 1)
        self.assertEqual(batch['counts']['duplicate'], 1)
        self.assertEqual(batch['counts']['failed'], 1)
        self.assertEqual(batch['settled'], 3)


class BatchEndpointTests(TestCase):
    """State survives navigation because it is fetched, not remembered."""

    def setUp(self):
        self.user = User.objects.create_user('ep_u', 'e@e.com', 'testpass123')
        self.other = User.objects.create_user('ep_o', 'o@e.com', 'testpass123')
        doc = make_doc(is_processed=True, duplicate_status='none')
        BackgroundJob.objects.create(
            job_type='bulk_upload_process', created_by=self.user, status='completed',
            payload={'document_ids': [doc.pk], 'total_count': 1},
        )

    def test_owner_sees_the_batch_on_a_fresh_request(self):
        client = self.client_class()
        client.login(username='ep_u', password='testpass123')
        payload = client.get(reverse('documents:upload_batches')).json()
        self.assertEqual(len(payload['batches']), 1)
        self.assertEqual(payload['batches'][0]['total'], 1)

    def test_another_user_does_not_see_it(self):
        client = self.client_class()
        client.login(username='ep_o', password='testpass123')
        self.assertEqual(client.get(reverse('documents:upload_batches')).json()['batches'], [])

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(reverse('documents:upload_batches')).status_code, 302)

    def test_state_is_identical_across_separate_sessions(self):
        # A "new tab" or "logged out and back in" is just another client.
        first = self.client_class()
        first.login(username='ep_u', password='testpass123')
        second = self.client_class()
        second.login(username='ep_u', password='testpass123')
        self.assertEqual(first.get(reverse('documents:upload_batches')).json(),
                         second.get(reverse('documents:upload_batches')).json())

    def test_recent_batches_is_newest_first(self):
        doc = make_doc(title='later', is_processed=True, duplicate_status='none')
        newer = BackgroundJob.objects.create(
            job_type='bulk_upload_process', created_by=self.user, status='completed',
            payload={'document_ids': [doc.pk], 'total_count': 1},
        )
        # Stamped explicitly. Both jobs are created within the same test, so
        # without distinct times the ordering is a coin toss and the assertion
        # was testing nothing.
        BackgroundJob.objects.filter(pk=newer.pk).update(
            created_at=timezone.now() + timezone.timedelta(minutes=5))

        batches = recent_batches(self.user)
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0]['job_id'], newer.pk)


class CurrentBatchTests(TestCase):
    """
    Which batch belongs on the upload page.

    Removing the old auto-hide fixed live batches disappearing and created the
    opposite fault: a batch that finished yesterday -- in one case with every
    document since deleted -- stayed pinned to the page on every visit.
    """

    def setUp(self):
        self.user = User.objects.create_user('cur_u', 'c@e.com', 'testpass123')

    def make_job(self, docs, age_hours=0, age_minutes=0, total=None):
        job = BackgroundJob.objects.create(
            job_type='bulk_upload_process', created_by=self.user, status='completed',
            payload={'document_ids': [d.pk for d in docs],
                     'total_count': total if total is not None else len(docs)},
        )
        if age_hours or age_minutes:
            BackgroundJob.objects.filter(pk=job.pk).update(
                created_at=timezone.now() - timezone.timedelta(
                    hours=age_hours, minutes=age_minutes))
        return BackgroundJob.objects.get(pk=job.pk)

    def test_unfinished_batch_is_current_however_old(self):
        doc = make_doc(is_processed=False, duplicate_status='pending_check')
        batch = batch_detail(self.make_job([doc], age_hours=72))
        self.assertFalse(batch['finished'])
        self.assertTrue(batch['is_current'], 'work in progress must never be hidden')

    def test_recently_finished_batch_is_current(self):
        """Coming back to the page a few minutes later still shows the result."""
        doc = make_doc(is_processed=True, duplicate_status='none')
        self.assertTrue(batch_detail(self.make_job([doc], age_minutes=10))['is_current'])

    def test_long_finished_batch_is_not_current(self):
        """
        The window is half an hour, not six.

        A finished batch is a result, and a result that has been on the page for
        hours is no longer news -- it is in the Repository, which is where the
        panel's own link points.
        """
        doc = make_doc(is_processed=True, duplicate_status='none')
        batch = batch_detail(self.make_job([doc], age_minutes=45))
        self.assertTrue(batch['finished'])
        self.assertFalse(batch['is_current'])

    def test_batch_whose_documents_were_all_deleted_is_not_current(self):
        doc = make_doc(is_processed=True, duplicate_status='none')
        job = self.make_job([doc])
        doc.delete()
        batch = batch_detail(job)
        self.assertEqual(batch['counts']['removed'], 1)
        self.assertFalse(batch['is_current'], 'nothing left to report')

    def test_a_partly_deleted_batch_is_still_worth_showing(self):
        kept = make_doc(title='kept', is_processed=True, duplicate_status='none')
        gone = make_doc(title='gone', is_processed=True, duplicate_status='none')
        job = self.make_job([kept, gone])
        gone.delete()
        self.assertTrue(batch_detail(job)['is_current'])


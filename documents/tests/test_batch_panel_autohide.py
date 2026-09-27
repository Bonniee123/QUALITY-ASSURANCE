"""
The finished batch panel takes itself off the upload page.

Two clocks decide how long the "Processing complete" card and its file list stay
under the drop zone, and both used to be far too long:

  * On the open page the card waited to be closed by hand, so the list sat there
    for as long as the tab was open. It now clears itself ten seconds after the
    batch settles, with the countdown visible while it runs -- a panel that
    disappears without saying it is about to looks the same as one that broke,
    which is why an earlier, silent auto-hide was taken out.

  * On a later visit the server decided whether the batch was still worth
    showing, and it answered yes for six hours. That window is now half an hour.

A batch that failed or stalled is excluded from the first rule: there the list
is still work, not a result, so it stays until it is dismissed.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from documents.models import BackgroundJob, Document
from documents.upload_batches import KEEP_FINISHED_FOR, batch_detail


def make_doc(**kwargs):
    fields = {
        'title': 'Batch panel document',
        'file': 'uploaded_documents/panel.pdf',
        'file_type': 'pdf',
        'year': 2026,
        'document_type': 'Report',
        'is_processed': True,
        'duplicate_status': 'none',
    }
    fields.update(kwargs)
    return Document.objects.create(**fields)


class KeepWindowTests(TestCase):
    """How long a settled batch is still reported to the page."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('panel_u', 'p@example.com', 'Str0ng-Passw0rd!')

    def job_aged(self, docs, minutes):
        job = BackgroundJob.objects.create(
            job_type='bulk_upload_process', created_by=self.user, status='completed',
            payload={'document_ids': [d.pk for d in docs], 'total_count': len(docs)},
        )
        BackgroundJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=minutes))
        return BackgroundJob.objects.get(pk=job.pk)

    def test_the_window_is_half_an_hour(self):
        self.assertEqual(KEEP_FINISHED_FOR, timezone.timedelta(minutes=30))

    def test_a_batch_that_settled_minutes_ago_is_still_shown(self):
        batch = batch_detail(self.job_aged([make_doc()], minutes=5))
        self.assertTrue(batch['finished'])
        self.assertTrue(batch['is_current'])

    def test_a_batch_that_settled_an_hour_ago_is_not(self):
        self.assertFalse(batch_detail(self.job_aged([make_doc()], minutes=60))['is_current'])

    def test_work_in_progress_is_never_hidden_by_age(self):
        """The window applies to results. Unfinished work is shown however old."""
        doc = make_doc(is_processed=False, duplicate_status='pending_check')
        batch = batch_detail(self.job_aged([doc], minutes=60 * 24))
        self.assertFalse(batch['finished'])
        self.assertTrue(batch['is_current'])


class PanelMarkupTests(TestCase):
    """The countdown is part of the page, not something the script invents."""

    @classmethod
    def setUpTestData(cls):
        cls.head = User.objects.create_user('panel_head', 'h@example.com', 'Str0ng-Passw0rd!')
        cls.head.profile.role = 'qa_staff'
        cls.head.profile.save()

    def page(self):
        self.client.force_login(self.head)
        return self.client.get(reverse('documents:bulk_upload')).content.decode()

    def test_the_countdown_element_is_rendered_hidden(self):
        html = self.page()
        self.assertIn('id="activeBatchAutohide"', html)
        head = html[html.index('id="activeBatchPanel"'):html.index('id="activeBatchItems"')]
        autohide = head[head.index('id="activeBatchAutohide"') - 60:]
        self.assertIn('d-none', autohide[:120], 'nothing counts down before a batch finishes')

    def test_the_close_button_stays(self):
        """Ten seconds is the default, not the only way out."""
        self.assertIn('id="activeBatchClose"', self.page())


class AutoHideScriptTests(SimpleTestCase):
    """The rules the page applies, read from the page itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (settings.BASE_DIR / 'templates' / 'documents'
                      / 'bulk_upload.html').read_text(encoding='utf-8')

    def test_the_delay_is_ten_seconds(self):
        self.assertIn('const AUTO_HIDE_SECONDS = 10;', self.source)

    def test_only_a_clean_finish_hides_itself(self):
        self.assertIn('if (done && !batch.stalled && !c.failed) {', self.source)

    def test_reading_the_panel_stops_the_clock(self):
        for hook in ('mouseenter', 'mouseleave', 'focusin', 'focusout'):
            self.assertIn("addEventListener('%s'" % hook, self.source)

    def test_the_countdown_is_shown_while_it_runs(self):
        """An unannounced disappearance reads as a failure; this one announces."""
        self.assertIn("'Hiding in '", self.source)

    def test_hiding_records_the_batch_as_dismissed(self):
        """Otherwise the next refresh of the batch state draws it again."""
        self.assertIn('rememberDismissed(autoHideBatchId);', self.source)

    def test_a_dismissed_batch_stays_dismissed_on_the_next_visit(self):
        """
        Reappearing on the next visit is the same lingering, one page load later.
        The id is kept in localStorage, and job ids only increase, so one number
        covers every batch already seen.
        """
        self.assertIn("const DISMISSED_KEY = 'qaDismissedBatch';", self.source)
        self.assertIn('localStorage.setItem(DISMISSED_KEY', self.source)
        self.assertIn('localStorage.getItem(DISMISSED_KEY)', self.source)

    def test_storage_being_unavailable_cannot_break_the_page(self):
        """Private mode throws on access; the tab's own memory carries on."""
        block = self.source[self.source.index('function rememberDismissed'):
                            self.source.index('function hydrateBatches')]
        self.assertEqual(block.count('catch (e)'), 2)

    def test_work_in_progress_is_never_hidden_by_a_dismissal(self):
        self.assertIn('if (batch.finished && wasDismissed(batch.job_id)) {', self.source)

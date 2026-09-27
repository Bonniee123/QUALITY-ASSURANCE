"""
The bulk-upload progress panel.

Three things were wrong with it. The bar and the percentage rendered in
Bootstrap's #0d6efd while the button beneath them is the brand #1a7b93, because
nothing in the project overrides --bs-primary -- two different "primary" colours
stacked in one panel. The bar carried role="progressbar" and no value, name,
minimum or maximum, so a screen reader was told a progress bar existed and never
what it read. And once every byte was sent the panel kept a striped, animated
bar at a measured 100% with the last transfer speed still on screen, claiming a
rate for a transfer that had finished while the server worked on.

A fourth, found while fixing those: Bootstrap's `.btn.disabled, .btn:disabled`
sets background-color at specificity (0,2,0), which outranks the (0,1,0)
`.btn-primary` rule in style.css. Every disabled primary button in the system
reverted to Bootstrap blue -- including this one, which is disabled for the
whole of an upload.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class UploadProgressMarkupTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('up_head', 'u@example.com', 'Str0ng-Passw0rd!')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()

    def page(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:bulk_upload')).content.decode()

    def test_the_bar_says_what_it_reads(self):
        html = self.page()
        for attribute in ('aria-valuenow="0"', 'aria-valuemin="0"',
                          'aria-valuemax="100"', 'aria-label="Upload progress"'):
            self.assertIn(attribute, html)

    def test_the_phase_is_announced_once_per_change(self):
        """One atomic status message, not a live region per number."""
        html = self.page()
        self.assertIn('id="uploadProgressLabel"', html)
        self.assertIn('role="status" aria-atomic="true"', html)

    def test_the_percentage_no_longer_takes_bootstraps_blue(self):
        html = self.page()
        self.assertNotIn('id="uploadProgressPct" class="fw-semibold text-primary"', html)
        self.assertIn('#uploadProgressPct { color: var(--color-brand) !important; }', html)

    def test_the_bar_takes_the_brand_colour(self):
        self.assertIn('.qa-upload-bar .progress-bar { background-color: var(--color-brand); }',
                      self.page())


class FinalizePhaseTests(TestCase):
    """What the panel does once the bytes are gone and the server is working."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('up_fin', 'f@example.com', 'Str0ng-Passw0rd!')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()

    def script(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:bulk_upload')).content.decode()

    def test_the_bar_stops_claiming_a_measured_value(self):
        body = self.script()
        self.assertIn("uploadProgressBar.setAttribute('aria-busy', 'true')", body)
        self.assertIn("uploadProgressBar.removeAttribute('aria-valuenow')", body)
        self.assertIn("classList.add('is-indeterminate')", body)

    def test_the_stale_speed_reading_is_cleared(self):
        """17.3 MB/s stayed on screen while nothing was being transferred."""
        self.assertIn("uploadProgressSpeed.textContent = ''", self.script())

    def test_the_button_says_which_phase_it_is_in(self):
        body = self.script()
        self.assertIn('Checking…', body)
        self.assertIn('setUploadBtnPhase(uploadBtnIdleHtml)', body,
                      'the idle label comes back when the request settles')

    def test_the_wait_is_not_described_as_finishing(self):
        """
        "Finalizing on server" said the outcome was settled while the server was
        still deciding: the request size- and type-checks each file, hashes it
        against the archive for an exact copy and compares it by picture for a
        visual one, and any of those refuses the file. A label promising a
        wrap-up was routinely followed by "3 file(s) not uploaded". It also read
        as the end of the step that comes after it, "preparing your files".
        """
        body = self.script()
        # The word survives in the comment that explains why it went; what
        # matters is that nothing assigns it to the label or the button.
        self.assertNotIn('uploadProgressLabel.innerHTML = \'<i class="bi bi-hourglass-split me-1"></i>Finalizing',
                         body)
        self.assertNotIn('setUploadBtnPhase(\'<i class="bi bi-hourglass-split me-2"></i>Finalizing', body)
        self.assertIn('Checking and saving your files…', body)
        self.assertIn('Uploaded — preparing your files…', body,
                      'the background phase keeps its own, later label')

    def test_a_finished_upload_publishes_a_value_again(self):
        self.assertEqual(self.script().count("setAttribute('aria-valuenow', '100')"), 2,
                         'one for success, one for failure')


class DisabledPrimaryButtonTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')

    def test_a_disabled_primary_button_keeps_the_brand_colour(self):
        """
        Bootstrap's rule is `.btn.disabled, .btn:disabled` at (0,2,0). A plain
        `.btn-primary:disabled` ties with it rather than beating it, and the tie
        was measured going Bootstrap's way, so the selector carries `.btn` too.
        """
        self.assertIn('.btn.btn-primary.disabled,.btn.btn-primary:disabled{'
                      'background-color:var(--color-brand)', self.css)

    def test_the_enabled_rule_is_untouched(self):
        self.assertIn('.btn-primary{background:var(--color-brand);'
                      'border-color:var(--color-brand);color:#fff}', self.css)


class UploadProgressMotionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('up_mot', 'm@example.com', 'Str0ng-Passw0rd!')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()

    def test_the_sweep_stops_for_a_reader_who_asked_for_less_motion(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('documents:bulk_upload')).content.decode()
        self.assertIn('@media (prefers-reduced-motion: reduce)', html)
        self.assertIn('.qa-upload-bar.is-indeterminate .progress-bar { animation: none;', html)


class PanelOrderTests(TestCase):
    """
    Results go under the action that produced them.

    The batch panel was the first thing inside the form, above the accreditation
    area, the programme selector and the drop zone. After a seven-file batch it
    was a tall card of results sitting between the top of the page and the
    upload controls, so uploading again meant scrolling past the last result to
    reach the thing you came to use.
    """

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('up_order', 'o@example.com', 'Str0ng-Passw0rd!')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()

    def body(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:bulk_upload')).content.decode()

    def test_the_batch_panel_comes_after_the_upload_controls(self):
        body = self.body()
        self.assertLess(body.index('id="dropZone"'), body.index('id="uploadBtn"'))
        self.assertLess(body.index('id="uploadBtn"'), body.index('id="activeBatchPanel"'))

    def test_the_panel_spaces_itself_from_what_is_above_it(self):
        self.assertIn('id="activeBatchPanel" class="d-none mt-4"', self.body())

    def test_the_panel_kept_everything_it_had(self):
        """Moving it must not cost it a control the script reaches for."""
        body = self.body()
        for hook in ('activeBatchCard', 'activeBatchIcon', 'activeBatchTitle', 'activeBatchHint',
                     'activeBatchCount', 'activeBatchClose', 'activeBatchBar',
                     'activeBatchFileCount', 'activeBatchItems'):
            self.assertIn('id="%s"' % hook, body)

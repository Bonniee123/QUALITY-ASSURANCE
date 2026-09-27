"""
The toast messages.

Three things were wrong with them. They were painted with Bootstrap's own
`text-bg-info` and `text-bg-warning`, #0dcaf0 and #ffc107 -- colours that appear
nowhere else in a system built on #1a7b93, #12784a, #8a6300 and #b02a21. The
fill was the only thing distinguishing one kind of message from another, so the
meaning rested on colour alone. And every toast carried role="alert", which is
assertive, so a routine "4 file(s) uploaded" cut across whatever a screen-reader
user was listening to.

The stack also sat at bottom:0 right:0 and rose straight over the QA Assistant
button, which is fixed at bottom:28px right:28px and is 56x56 -- every message
covered the control.

Text contrast was never the problem: black on #0dcaf0 measures 10.72:1 and on
#ffc107 12.88:1. The replacement is #023047 on white at 13.85:1, with the rail
and icon at 4.89:1 (brand), 5.43:1 (warning) and 6.56:1 (danger), all above the
3:1 a non-text indicator needs.
"""
from django.conf import settings
from django.test import SimpleTestCase


class ToastScriptTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (settings.BASE_DIR / 'static' / 'js' / 'main.js').read_text(encoding='utf-8')

    def test_the_bootstrap_fills_are_gone(self):
        # The names survive in the comment explaining why they went; what
        # matters is that nothing puts them on the element.
        self.assertNotIn("'toast align-items-center text-bg-'", self.js)
        self.assertIn("el.className = 'toast border-0 mb-2 qa-toast-item qa-toast--'", self.js)
        self.assertNotIn('btn-close-white', self.js)

    def test_each_kind_of_message_carries_its_own_icon(self):
        """Colour alone cannot be the difference between done and refused."""
        for icon in ('bi-check-circle-fill', 'bi-x-circle-fill',
                     'bi-exclamation-triangle-fill', 'bi-info-circle-fill'):
            self.assertIn(icon, self.js)

    def test_only_a_failure_interrupts(self):
        self.assertIn("role: 'alert'", self.js)
        self.assertIn("role: 'status'", self.js)
        self.assertEqual(self.js.count("role: 'alert'"), 2, 'error and danger, nothing else')

    def test_the_close_button_is_named(self):
        self.assertIn("aria-label=\"Dismiss this message\"", self.js)


class ToastStyleTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')

    def test_the_stack_clears_the_assistant_button(self):
        """
        Centred under the navbar, which is what keeps it clear of both the
        floating Messages button in the bottom-right corner and the page
        content underneath it.
        """
        self.assertIn('.qa-toast-container{position:fixed;top:calc(var(--navbar-height) + 14px);'
                      'left:50%;transform:translateX(-50%);', self.css)
        self.assertNotIn('bottom:96px', self.css)

    def test_a_toast_takes_the_page_surface_and_a_semantic_rail(self):
        self.assertIn('background:var(--color-surface)', self.css)
        self.assertIn('border-left:3px solid var(--qa-toast-accent,var(--color-brand))', self.css)
        for rule in ('.qa-toast--success{--qa-toast-accent:var(--color-success)}',
                     '.qa-toast--warning{--qa-toast-accent:var(--color-warning)}',
                     '.qa-toast--danger{--qa-toast-accent:var(--color-danger)}',
                     '.qa-toast--info{--qa-toast-accent:var(--color-brand)}'):
            self.assertIn(rule, self.css)

    def test_the_close_target_reaches_the_minimum(self):
        """It measured 23x24; a pointer target needs 24 CSS pixels."""
        self.assertIn('.qa-toast-container .btn-close{width:24px;height:24px;', self.css)

    def test_the_text_is_off_the_twelve_pixel_floor(self):
        """
        The width moved with the stack -- centred under the navbar there is room
        for 420px, where a bottom-right corner had room for 340 -- so this holds
        the part that was the point: the type size.
        """
        self.assertIn('font-size:13px;', self.css)
        self.assertIn('max-width:420px;font-size:13px;', self.css)


class ToastContainerTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = (settings.BASE_DIR / 'templates' / 'base.html').read_text(encoding='utf-8')

    def test_the_position_utilities_are_gone(self):
        """
        Bootstrap's bottom-0 and end-0 are !important, so the position could not
        be corrected from the stylesheet while they were on the element.
        """
        self.assertNotIn('qa-toast-container position-fixed bottom-0 end-0', self.base)
        self.assertIn('class="toast-container qa-toast-container" id="qaToastContainer"', self.base)

    def test_the_container_still_announces_politely(self):
        self.assertIn('aria-live="polite" aria-atomic="true"', self.base)

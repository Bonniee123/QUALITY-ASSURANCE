"""
The dashboard toolbar: what reads as a control, and what does not.

Five pills sat in a row. Measured, the two that report state and the three that
do something were identical -- background rgb(255,255,255), border
rgb(203,225,236), radius 10px, padding 8px 14px, 13px at weight 500 -- so the
only thing telling a reader that "Updated 12:41 PM" cannot be clicked was the
absence of a caret.

The second of them, at 282px, was also the widest thing in the row, and half of
it ("Last 6 months") repeated the control immediately to its right, whose menu
already reads "Monthly (6 months)". Between them the row overflowed its 881px
onto a second line by a single pixel.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


def make_user(username, role):
    user = User.objects.create_user(username, password='Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    return user


class PeriodLabelTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('bar_admin', 'admin')

    def page(self, period=''):
        self.client.force_login(self.admin)
        url = reverse('dashboard:home') + ('?period=' + period if period else '')
        return self.client.get(url)

    def test_the_toolbar_shows_the_dates_and_not_the_phrase_beside_them(self):
        """"Last 6 months" is what the period control's own menu already says."""
        response = self.page('monthly')
        self.assertNotIn('Last 6 months', response.context['period_range'])
        self.assertIn('Last 6 months', response.context['period_label'])
        self.assertIn('–', response.context['period_range'], 'an en dash between the dates')

    def test_every_period_has_a_range(self):
        for period, phrase in (('daily', 'Last 30 days'),
                               ('weekly', 'Last 12 weeks'),
                               ('monthly', 'Last 6 months')):
            with self.subTest(period=period):
                context = self.page(period).context
                self.assertTrue(context['period_range'])
                self.assertNotIn(phrase, context['period_range'])
                self.assertIn(phrase, context['period_label'])

    def test_the_chart_description_keeps_the_full_phrase(self):
        """A screen reader has no control beside the chart to borrow the period from."""
        body = self.page('monthly').content.decode()
        self.assertIn('Last 6 months', body)

    def test_the_status_readouts_are_no_longer_dressed_as_controls(self):
        body = self.page().content.decode()
        self.assertEqual(body.count('nx-readout'), 3, 'both readouts, one of them live')
        self.assertNotIn('nx-chip', body)

    def test_the_controls_are_still_controls(self):
        body = self.page().content.decode()
        start = body.index('class="nx-actions"')
        toolbar = body[start:body.index('nx-section-title', start)]
        self.assertIn('nx-btn-primary', toolbar)
        self.assertIn('Export Excel', toolbar)
        self.assertEqual(toolbar.count('data-bs-toggle="dropdown"'), 2, 'period and programme')
        self.assertIn('nx-actions-rule', toolbar, 'the rule between reading and pressing')


class ToolbarStyleTests(SimpleTestCase):
    """The stylesheet rules the toolbar depends on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'nexus.css').read_text(encoding='utf-8')

    def test_a_readout_carries_no_button_chrome(self):
        start = self.css.index('.nx-readout {')
        rule = self.css[start:self.css.index('}', start)]
        self.assertNotIn('border:', rule)
        self.assertNotIn('background', rule)
        self.assertNotIn('border-radius', rule)

    def test_the_separator_is_a_block_so_it_can_have_a_size(self):
        """A span is inline, and width/height do not apply -- it measured 0x0."""
        start = self.css.index('.nx-actions-rule {')
        rule = self.css[start:self.css.index('}', start)]
        self.assertIn('display: block;', rule)
        self.assertIn('width: 1px;', rule)

    def test_the_controls_reach_a_touch_size_on_a_phone(self):
        self.assertIn('.nx-btn { min-height: 44px;', self.css)

    def test_the_old_chip_class_is_gone_rather_than_left_behind(self):
        self.assertNotIn('.nx-chip', self.css)

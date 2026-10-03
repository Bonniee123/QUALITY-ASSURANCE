"""
What the KPI tiles are allowed to claim.

Two cards sat side by side each reading "80 ^ 100.0%". Neither percentage was
measured: `_kpi_delta` returned a hardcoded "100.0" whenever the previous
period was empty, which on this archive is both of them -- every document was
uploaded inside one twelve-minute window, so the previous 7 days and the
previous 30 days each held nothing. Growth from zero is undefined, not a
hundred per cent.

The Total Documents tile made it worse by carrying that badge at all: it counts
the whole archive, so there is no period for it to be compared against.

These rules are role-independent. The comparison is computed the same way for
Admin, QA staff and Faculty, and each of them is checked here.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard.views import _kpi_delta
from documents.models import Document
from qa_structure.models import AccreditationArea


class DeltaArithmeticTests(SimpleTestCase):

    def test_nothing_to_compare_against_is_not_a_hundred_per_cent(self):
        self.assertEqual(_kpi_delta(80, 0), {'pct': '', 'dir': 'new'})

    def test_an_empty_period_after_an_empty_period_is_flat(self):
        self.assertEqual(_kpi_delta(0, 0), {'pct': '0.0', 'dir': 'flat'})

    def test_a_real_doubling_still_reads_as_a_hundred_per_cent(self):
        self.assertEqual(_kpi_delta(10, 5), {'pct': '100.0', 'dir': 'up'})

    def test_a_fall_is_reported_as_a_fall(self):
        self.assertEqual(_kpi_delta(5, 10), {'pct': '50.0', 'dir': 'down'})

    def test_no_change_is_flat(self):
        self.assertEqual(_kpi_delta(7, 7), {'pct': '0.0', 'dir': 'flat'})


def make_user(username, role, areas=()):
    user = User.objects.create_user(username, password='Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    for area in areas:
        user.profile.assigned_areas.add(area)
    return user


class KpiCardTests(TestCase):
    """Every role sees the same arithmetic and the same affordances."""

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area III', defaults={'area_name': 'Curriculum'})
        for n in range(3):
            Document.objects.create(
                title=f'Evidence {n}', file=f'uploaded_documents/e{n}.pdf', file_type='pdf',
                year=2026, document_type='Report', acc_area=cls.area, qa_area='Area III')
        cls.roles = {
            'admin': make_user('kpi_admin', 'admin'),
            'qa_staff': make_user('kpi_staff', 'qa_staff'),
            'faculty': make_user('kpi_faculty', 'faculty', [cls.area]),
        }

    def dashboard_for(self, role):
        self.client.force_login(self.roles[role])
        return self.client.get(reverse('dashboard:home')).content.decode()

    @staticmethod
    def delta_text(html):
        """The words inside every change badge on the page."""
        import re
        return ' '.join(re.sub(r'<[^>]+>', ' ', m) for m in
                        re.findall(r'<span class="nx-delta[^"]*"[^>]*>(.*?)</span>', html, re.S))

    def test_no_role_is_shown_an_invented_percentage(self):
        """Uploaded just now, nothing in the previous week: there is no figure."""
        for role in self.roles:
            with self.subTest(role=role):
                html = self.dashboard_for(role)
                self.assertNotIn('100.0%', html)
                self.assertIn('nx-delta-new', html)
                self.assertIn('New', self.delta_text(html))
                # The 'No uploads in the previous 7 days' footer line was removed
                # from the card: the rail cards carry no caption now. The state
                # is still stated, in the 'New' badge above.
                self.assertNotIn('No uploads in the previous 7 days', html)

    def test_total_documents_carries_no_change_badge_for_any_role(self):
        for role in self.roles:
            with self.subTest(role=role):
                html = self.dashboard_for(role)
                self.assertNotIn('Change vs. previous 30 days', html)
                self.assertIn('Change vs. previous 7 days', html)

    def test_a_real_comparison_is_still_reported(self):
        """Backdate the three uploads a week and add two more: a genuine fall."""
        week_ago = timezone.now() - timedelta(days=9)
        Document.objects.update(uploaded_at=week_ago)
        for n in range(2):
            Document.objects.create(
                title=f'Newer {n}', file=f'uploaded_documents/n{n}.pdf', file_type='pdf',
                year=2026, document_type='Report', acc_area=self.area, qa_area='Area III')
        html = self.dashboard_for('admin')
        self.assertIn('33.3%', html)
        self.assertNotIn('nx-delta-new', html)
        # The comparison is the badge, not a footer sentence: 'Last 7 days vs.
        # previous 7' was the caption line the card no longer carries. What the
        # test proves is that a real change is stated as a percentage.
        self.assertNotIn('Last 7 days vs. previous 7', html)


class KpiAffordanceTests(SimpleTestCase):
    """The stylesheet rules the cards depend on, checked as text."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.conf import settings
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'nexus.css').read_text(encoding='utf-8')

    def test_the_link_arrow_is_not_hidden_until_hover(self):
        """A touch screen has no hover, so opacity:0 meant no affordance at all."""
        self.assertNotIn('opacity: 0;\n    transform: translateX(-4px);', self.css)
        self.assertIn('.nx-kpi-link:focus-visible .nx-kpi-go', self.css)

    def test_the_footer_is_pinned_to_the_bottom_of_the_tile(self):
        self.assertIn('.nx-kpi .nx-kpi-foot { font-size: 12px; margin-top: auto;', self.css)

    def test_the_no_baseline_badge_has_a_style(self):
        self.assertIn('.nx-delta-new {', self.css)

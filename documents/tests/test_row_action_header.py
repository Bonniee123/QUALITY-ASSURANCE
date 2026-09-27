"""
The Actions column names itself.

The kebab toggle carried `title="Actions"`, a tooltip that repeated the same
word one row at a time and only for a reader using a mouse, while the column
header hid that word behind `visually-hidden`. The header now says it in the
open, once, for every row at a time -- which is what the User Management and
Area Submissions tables already do.

`aria-label` stays. It is the button's accessible name, not a tooltip, and an
icon-only control has to carry one.
"""
from django.contrib.auth.models import User
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from documents.models import Document
from qa_mapping.models import QAProgram
from qa_structure.models import AccreditationArea


class ActionsHeaderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.program, _ = QAProgram.objects.get_or_create(
            code='ACCRED', defaults={'name': 'Accreditation', 'is_active': True})
        cls.head = User.objects.create_user('hdr_head', 'h@example.com', 'Str0ng-Passw0rd!')
        cls.head.profile.role = 'qa_staff'
        cls.head.profile.save()
        Document.objects.create(
            title='Filed evidence', file='uploaded_documents/e.pdf', file_type='pdf',
            year=2026, document_type='Report', program=cls.program,
            acc_area=cls.area, qa_area='Area II', uploaded_by=cls.head)

    def page(self, name, *args):
        self.client.force_login(self.head)
        return self.client.get(reverse(name, args=args)).content.decode()

    def test_both_tables_show_the_word(self):
        for page in (self.page('documents:repository'),
                     self.page('documents:group_detail', 'ACCRED')):
            self.assertIn('<th class="repo-col-actions text-end">Actions</th>', page)
            self.assertNotIn('<span class="visually-hidden">Actions</span>', page)

    def test_the_toggle_has_no_tooltip(self):
        for page in (self.page('documents:repository'),
                     self.page('documents:group_detail', 'ACCRED')):
            self.assertNotIn('title="Actions"', page)

    def test_the_toggle_keeps_its_accessible_name(self):
        """An icon-only button without a name is unusable with a screen reader."""
        page = self.page('documents:repository')
        self.assertIn('aria-label="Actions for Filed evidence"', page)

    def test_the_column_gutter_is_trimmed_to_fit_the_word(self):
        """
        The word costs the column about 21px. At 1366px the Repository table had
        nothing to spare, so the gutter on this column drops from 12px to 6px.
        """
        self.assertIn('> .repo-col-actions { padding-left: 6px; padding-right: 6px; }',
                      self.page('documents:repository'))


class KebabTooltipTests(SimpleTestCase):
    """
    The hover tooltip was drawn in CSS, not by the browser.

    `.act::after { content: attr(title) }` paints its own pill, and that pill
    carries a background, padding and a radius of its own. Removing the `title`
    attribute left the content empty but the box intact, so hovering the kebab
    still produced a small empty dark chip above it. The pseudo-element is
    switched off for this button. User Management still uses the same `.act`
    chips with real titles, so the rule itself stays.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')

    def test_the_toggle_draws_no_tooltip_box(self):
        self.assertIn('.qa-row-menu-toggle::after { content: none; }', self.css)

    def test_the_chips_that_still_need_one_keep_it(self):
        self.assertIn('.act::after {', self.css)
        self.assertIn('content: attr(title);', self.css)


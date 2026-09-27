"""
One set of actions in the document detail modal, not two.

View, Download and Edit appeared twice: as unlabelled icon buttons in the modal
header and as labelled buttons at the top of the panel below, three inches
apart, doing the same three things. The labelled row stays -- it names each
action rather than leaving it to a glyph and a hover tooltip, and it sits beside
the title and filename it acts on.

The icons also carried a second permission rule. `data-can-edit` was computed
from the role alone, so it could not know whether a Faculty member owns the
document, while the panel's own Edit button checks exactly that. Removing the
icons removes the divergent rule with them.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class ModalHeaderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.head = User.objects.create_user('modal_head', 'm@example.com', 'Str0ng-Passw0rd!')
        cls.head.profile.role = 'qa_staff'
        cls.head.profile.save()

    def page(self):
        self.client.force_login(self.head)
        return self.client.get(reverse('documents:repository')).content.decode()

    def test_the_header_keeps_only_the_close_button(self):
        html = self.page()
        header = html[html.index('id="qaDocDetailModal"'):html.index('id="qaDocDetailBody"')]
        for gone in ('id="qaDocDetailView"', 'id="qaDocDetailDownload"', 'id="qaDocDetailEdit"'):
            self.assertNotIn(gone, header)
        self.assertIn('btn-close', header)

    def test_the_second_permission_rule_is_gone(self):
        self.assertNotIn('data-can-edit', self.page())

    def test_the_view_url_template_left_with_the_icon_that_used_it(self):
        self.assertNotIn('data-view-url-template', self.page())

    def test_the_panel_url_template_stays(self):
        """It is how the modal loads its body."""
        self.assertIn('data-panel-url-template', self.page())


class PanelActionsTests(TestCase):
    """The surviving row still offers all three, under the right conditions."""

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.owner = User.objects.create_user('modal_owner', 'o@example.com', 'Str0ng-Passw0rd!')
        cls.owner.profile.role = 'faculty'
        cls.owner.profile.save()
        cls.owner.profile.assigned_areas.add(cls.area)
        cls.doc = Document.objects.create(
            title='Filed evidence', file='uploaded_documents/e.pdf', file_type='pdf',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            uploaded_by=cls.owner)

    def test_every_action_is_named_in_words(self):
        self.client.force_login(self.owner)
        panel = self.client.get(
            reverse('documents:detail', args=[self.doc.pk]) + '?panel=1').content.decode()
        actions = panel[panel.index('<!-- Quick actions -->'):panel.index('<div class="row g-3">')]
        for label in ('View File', 'Download', 'Edit'):
            self.assertEqual(actions.count(label), 1, '%s appears once' % label)
        self.assertEqual(panel.count('js-qa-doc-edit'), 1, 'one Edit, not two')


class DetailScriptTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (settings.BASE_DIR / 'static' / 'js' / 'doc-detail.js').read_text(encoding='utf-8')

    def test_the_wiring_for_the_removed_icons_is_gone(self):
        for gone in ('qaDocDetailView', 'qaDocDetailDownload', 'qaDocDetailEdit',
                     'canEdit', 'viewUrlTemplate', 'activeDownloadUrl'):
            self.assertNotIn(gone, self.js)

    def test_the_public_entry_point_still_takes_its_three_arguments(self):
        """doc-edit.js calls it with three; the third is accepted and ignored."""
        self.assertIn('function openDetail(docId, title, downloadUrl)', self.js)
        self.assertIn('window.qaOpenDocDetail = openDetail;', self.js)

"""
The row actions are one menu, and it is the same menu on every document table.

Five icon chips ended every row of the Repository and of a group page; the
actions now live in a kebab menu rendered from a single partial. What matters
here is that the redesign kept all five actions, kept the hooks the detail
panel, edit panel and delete modal listen for, and kept the two permission
conditions -- and that it replaced the icon row rather than adding a second way
to reach the same URLs.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_mapping.models import QAProgram
from qa_structure.models import AccreditationArea


def make_user(username, role, areas=()):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    for area in areas:
        user.profile.assigned_areas.add(area)
    return user


class RowActionMenuTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.program, _ = QAProgram.objects.get_or_create(
            code='ACCRED', defaults={'name': 'Accreditation', 'is_active': True})
        cls.head = make_user('menu_head', 'qa_staff')
        cls.faculty = make_user('menu_faculty', 'faculty', areas=[cls.area])
        cls.someone_elses = Document.objects.create(
            title='Minutes of the council', file='uploaded_documents/a.pdf', file_type='pdf',
            year=2026, document_type='Minutes', program=cls.program, acc_area=cls.area,
            qa_area='Area II', uploaded_by=cls.head)

    def repository(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('documents:repository')).content.decode()

    def test_one_menu_holds_every_action(self):
        body = self.repository(self.head)
        self.assertEqual(body.count('qa-row-menu-toggle'), 1, 'one menu per row')
        for hook in (reverse('documents:view', args=[self.someone_elses.pk]),
                     reverse('documents:download', args=[self.someone_elses.pk]),
                     'js-qa-doc-detail', 'js-qa-doc-edit',
                     f'data-qa-delete-url="{reverse("documents:delete", args=[self.someone_elses.pk])}"'):
            self.assertIn(hook, body)

    def test_the_actions_are_named_in_words(self):
        """The icon row left the meaning to a glyph and a hover tooltip."""
        body = self.repository(self.head)
        for label in ('>View file<', '>Details<', '>Download<', '>Edit<', '>Delete<'):
            self.assertIn(label, body)

    def test_the_icon_row_is_gone_rather_than_duplicated(self):
        self.assertNotIn('action-group', self.repository(self.head))

    def test_a_faculty_menu_offers_only_what_they_may_do(self):
        body = self.repository(self.faculty)
        self.assertEqual(body.count('qa-row-menu-toggle'), 1)
        self.assertIn('js-qa-doc-detail', body)
        self.assertNotIn('js-qa-doc-edit', body)
        self.assertNotIn('data-qa-delete-url', body)

    def test_a_group_page_uses_the_same_menu(self):
        self.client.force_login(self.head)
        body = self.client.get(reverse('documents:group_detail', args=['ACCRED'])).content.decode()
        self.assertEqual(body.count('qa-row-menu-toggle'), 1)
        self.assertNotIn('action-group', body)

    def test_the_menu_escapes_the_panel_that_would_clip_it(self):
        """Without a fixed strategy the last rows' menus were cut off."""
        self.assertIn('data-bs-popper-config', self.repository(self.head))

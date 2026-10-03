"""
A page per QA programme.

The Repository can filter to a programme, but that is a search: the category
lived only as a badge beside a title and a dropdown option. These pages give
each group a place of its own, under the same area scoping as everything else --
a Faculty member opening a group sees their own areas and nothing more.
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


class DocumentGroupTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Areas and programmes are seeded by migrations; take what is there.
        cls.area_two, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.area_three, _ = AccreditationArea.objects.get_or_create(
            area_code='Area III', defaults={'area_name': 'Curriculum and Instruction'})
        cls.accred, _ = QAProgram.objects.get_or_create(
            code='ACCRED', defaults={'name': 'Accreditation', 'is_active': True})
        cls.iso, _ = QAProgram.objects.get_or_create(
            code='ISO-INT', defaults={'name': 'ISO Internal Quality Audit', 'is_active': True})

        cls.in_area_two = Document.objects.create(
            title='Faculty profile matrix', file='uploaded_documents/a.pdf', file_type='pdf',
            year=2026, document_type='Report', program=cls.accred, acc_area=cls.area_two,
            qa_area='Area II', is_processed=True)
        cls.in_area_three = Document.objects.create(
            title='Curriculum compliance report', file='uploaded_documents/b.pdf', file_type='pdf',
            year=2026, document_type='Report', program=cls.accred, acc_area=cls.area_three,
            qa_area='Area III', is_processed=True)
        cls.no_category = Document.objects.create(
            title='Loose minutes', file='uploaded_documents/c.pdf', file_type='pdf',
            year=2026, document_type='Minutes', acc_area=cls.area_two, qa_area='Area II')

        cls.admin = make_user('grp_admin', 'admin')
        cls.faculty = make_user('grp_faculty', 'faculty', areas=[cls.area_two])

        # Same area as the faculty member, but theirs. The row above is not.
        cls.faculty_own = Document.objects.create(
            title='My own evidence', file='uploaded_documents/d.pdf', file_type='pdf',
            year=2026, document_type='Report', program=cls.accred, acc_area=cls.area_two,
            qa_area='Area II', uploaded_by=cls.faculty, is_processed=True,
            duplicate_status='possible')

    def test_the_index_lists_the_programmes_that_exist(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse('documents:groups'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Accreditation')
        self.assertContains(page, 'ISO Internal Quality Audit')
        self.assertContains(page, 'No category')

    def test_a_group_page_lists_that_group_only(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse('documents:group_detail', args=['ACCRED']))
        self.assertContains(page, 'Faculty profile matrix')
        self.assertContains(page, 'Curriculum compliance report')
        self.assertNotContains(page, 'Loose minutes')

    def test_a_faculty_member_sees_only_their_own_area_in_a_group(self):
        self.client.force_login(self.faculty)
        page = self.client.get(reverse('documents:group_detail', args=['ACCRED']))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Faculty profile matrix')
        self.assertNotContains(page, 'Curriculum compliance report')

    def test_the_counts_follow_the_same_scope(self):
        self.client.force_login(self.faculty)
        page = self.client.get(reverse('documents:groups'))
        self.assertEqual(page.context['total_files'], 3, 'their three Area II documents, nothing else')
        accred = next(g for g in page.context['groups'] if g['program'].code == 'ACCRED')
        self.assertEqual(accred['files'], 2)

    def test_documents_without_a_programme_have_their_own_page(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse('documents:group_detail', args=['unassigned']))
        self.assertContains(page, 'Loose minutes')
        self.assertNotContains(page, 'Faculty profile matrix')

    def test_an_unknown_group_is_not_found(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('documents:group_detail', args=['NOPE'])).status_code, 404)

    def delete_link(self, doc):
        return f'data-qa-delete-url="{reverse("documents:delete", args=[doc.pk])}"'

    def test_a_group_page_offers_the_same_actions_as_the_repository(self):
        """Edit and delete were missing here; staff may use both on any file."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse('documents:group_detail', args=['ACCRED']))
        body = page.content.decode()
        self.assertEqual(body.count('js-qa-doc-edit'), 3, 'one edit button per row')
        self.assertIn(self.delete_link(self.in_area_two), body)
        self.assertIn(self.delete_link(self.faculty_own), body)

    def test_a_faculty_member_may_only_act_on_their_own_upload(self):
        self.client.force_login(self.faculty)
        page = self.client.get(reverse('documents:group_detail', args=['ACCRED']))
        body = page.content.decode()
        self.assertIn(self.delete_link(self.faculty_own), body)
        self.assertNotIn(self.delete_link(self.in_area_two), body,
                         'someone else\'s upload in their area is not theirs to delete')
        self.assertEqual(body.count('js-qa-doc-edit'), 1)

    def test_the_server_refuses_what_the_buttons_hide(self):
        """Hiding the control is not the control: the view enforces the rule."""
        self.client.force_login(self.faculty)
        response = self.client.post(reverse('documents:delete', args=[self.in_area_two.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Document.objects.filter(pk=self.in_area_two.pk).exists())

    def test_faculty_are_not_shown_duplicate_review_information(self):
        """Resolving a duplicate is QA work, so the column and the counts are not theirs."""
        self.client.force_login(self.faculty)
        detail = self.client.get(reverse('documents:group_detail', args=['ACCRED'])).content.decode()
        self.assertNotIn('<th>Review</th>', detail)
        self.assertNotIn('to review', detail)
        index = self.client.get(reverse('documents:groups')).content.decode()
        self.assertNotIn('to review', index)

    def test_staff_keep_the_review_column_and_counts(self):
        self.client.force_login(self.admin)
        detail = self.client.get(reverse('documents:group_detail', args=['ACCRED'])).content.decode()
        self.assertIn('<th>Review</th>', detail)
        self.assertIn('to review', detail)
        self.assertIn('to review', self.client.get(reverse('documents:groups')).content.decode())

    def test_faculty_may_correct_their_own_upload(self):
        """A wrong file they uploaded is theirs to replace: edit it or delete it."""
        self.client.force_login(self.faculty)
        page = self.client.get(reverse('documents:group_detail', args=['ACCRED']))
        body = page.content.decode()
        self.assertIn(self.delete_link(self.faculty_own), body)
        self.assertIn('js-qa-doc-edit', body)
        removed = self.client.post(reverse('documents:delete', args=[self.faculty_own.pk]))
        self.assertEqual(removed.status_code, 302)
        # Reversible: gone from the group page, restorable for ten seconds.
        self.assertFalse(Document.objects.live().filter(pk=self.faculty_own.pk).exists())
        self.assertTrue(Document.objects.deleted().filter(pk=self.faculty_own.pk).exists())

    def test_signing_in_is_required(self):
        response = self.client.get(reverse('documents:groups'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response.url)

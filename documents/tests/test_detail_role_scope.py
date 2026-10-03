"""
What a Faculty member is shown in Document Details.

The panel was the same for every role. A Faculty member saw the duplicate
verdict, the AI cluster, the OCR status and the raw text of any pipeline error,
and was offered an Edit button on a colleague's file -- while the Repository
beside it already hid its Duplicate column from them, and the Clusters page
they would need to act on a cluster is QA staff only.

Duplicate work is QA work: the matches are no longer merely hidden in the
template, they are never put in the page. Hiding a panel while shipping its
contents in the HTML is not scoping.

What a Faculty member keeps is what an uploader needs: the file, its metadata,
who filed it and when, and whether processing finished.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


def make_user(username, role, areas=()):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    for area in areas:
        user.profile.assigned_areas.add(area)
    return user


class DetailPanelRoleScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.owner = make_user('scope_owner', 'faculty', [cls.area])
        cls.peer = make_user('scope_peer', 'faculty', [cls.area])
        cls.head = make_user('scope_head', 'qa_staff')

        cls.other = Document.objects.create(
            title='Sibling evidence', file='uploaded_documents/sib.pdf', file_type='pdf',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            uploaded_by=cls.head)
        cls.doc = Document.objects.create(
            title='My evidence', file='uploaded_documents/mine.pdf', file_type='pdf',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            uploaded_by=cls.owner, cluster_label=7, duplicate_status='possible',
            ocr_status='failed', ocr_error='tesseract exited with code 1',
            processing_error='extractor raised ValueError',
            similar_documents=[{'id': cls.other.pk, 'title': 'Sibling evidence',
                                'similarity': 0.93, 'match_type': 'text'}])

    def panel(self, user):
        self.client.force_login(user)
        return self.client.get(
            reverse('documents:detail', args=[self.doc.pk]) + '?panel=1').content.decode()

    def test_staff_still_see_the_whole_panel(self):
        html = self.panel(self.head)
        for item in ('>Cluster</span>', 'Duplicate Check', 'OCR Status',
                     'Similar Documents', 'Sibling evidence'):
            self.assertIn(item, html)

    def test_faculty_are_not_shown_qa_work(self):
        html = self.panel(self.owner)
        for item in ('>Cluster</span>', 'Duplicate Check', 'OCR Status', 'Similar Documents'):
            self.assertNotIn(item, html)

    def test_the_matches_are_not_in_the_page_at_all(self):
        """Not hidden by CSS or a template tag -- absent."""
        html = self.panel(self.owner)
        self.assertNotIn('Sibling evidence', html)
        self.assertNotIn('tesseract exited with code 1', html)
        self.assertNotIn('extractor raised ValueError', html)

    def test_the_view_hands_faculty_nothing_to_hide(self):
        self.client.force_login(self.owner)
        context = self.client.get(
            reverse('documents:detail', args=[self.doc.pk]) + '?panel=1').context
        self.assertEqual(list(context['similar_docs']), [])
        self.assertEqual(context['similar_total'], 0)
        self.assertEqual(list(context['cluster_docs']), [])

    def test_faculty_keep_what_an_uploader_needs(self):
        html = self.panel(self.owner)
        for item in ('My evidence', 'Metadata', '>Processing<', 'QA Area / Criterion',
                     'Uploaded By', 'Download', 'View File'):
            self.assertIn(item, html)

    def test_edit_is_offered_on_their_own_upload_only(self):
        """The row menu already carried this condition; the panel had none."""
        self.assertIn('js-qa-doc-edit', self.panel(self.owner))
        self.assertNotIn('js-qa-doc-edit', self.panel(self.peer))
        self.assertIn('js-qa-doc-edit', self.panel(self.head))


class RepositoryClusterScopeTests(TestCase):
    """The cluster column, its sort and its filter leave together."""

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.faculty = make_user('clus_fac', 'faculty', [cls.area])
        cls.head = make_user('clus_head', 'qa_staff')
        Document.objects.create(
            title='Filed evidence', file='uploaded_documents/f.pdf', file_type='pdf',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            uploaded_by=cls.faculty, cluster_label=3)

    def repository(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('documents:repository')).content.decode()

    def test_staff_keep_the_cluster_column_and_filter(self):
        html = self.repository(self.head)
        self.assertIn('id="fCluster"', html)
        self.assertIn('data-sort="cluster"', html)

    def test_faculty_get_neither(self):
        html = self.repository(self.faculty)
        self.assertNotIn('id="fCluster"', html)
        self.assertNotIn('data-sort="cluster"', html)

    def test_the_row_matches_the_header_for_both_roles(self):
        for user in (self.head, self.faculty):
            with self.subTest(role=user.profile.role):
                html = self.repository(user)
                head = html[html.index('<thead>'):html.index('</thead>')]
                head = head.replace('<thead>', '')  # otherwise it counts as a <th
                row = html[html.index('class="doc-row'):]
                row = row[:row.index('</tr>')]
                self.assertEqual(head.count('<th'), row.count('<td'))
                self.assertEqual(row.count('<td'),
                                 12 if user.profile.role == 'qa_staff' else 9)

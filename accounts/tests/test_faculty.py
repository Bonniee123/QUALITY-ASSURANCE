"""Tests for the area-scoped Faculty role."""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class FacultyRoleTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        self.area3, _ = AccreditationArea.objects.get_or_create(
            area_code='Area III', defaults={'area_name': 'Curriculum'})

        self.admin = User.objects.create_user('fac_admin', 'a@test.com', 'pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

        self.faculty = User.objects.create_user('fac_user', 'f@test.com', 'pass12345')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()
        self.faculty.profile.assigned_areas.set([self.area2])

        self.other_faculty = User.objects.create_user('fac_other', 'o@test.com', 'pass12345')
        self.other_faculty.profile.role = 'faculty'
        self.other_faculty.profile.save()
        self.other_faculty.profile.assigned_areas.set([self.area3])

        # Document inside the faculty's area, uploaded by someone else.
        self.doc_area2 = Document.objects.create(
            title='Area2 Doc', file='uploaded_documents/2026/05/a2.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area II', acc_area=self.area2,
            uploaded_by=self.admin,
        )
        # Document the faculty uploaded themselves (own).
        self.doc_own = Document.objects.create(
            title='My Own Doc', file='uploaded_documents/2026/05/own.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area II', acc_area=self.area2,
            uploaded_by=self.faculty,
        )
        # Document outside the faculty's area.
        self.doc_area3 = Document.objects.create(
            title='Area3 Doc', file='uploaded_documents/2026/05/a3.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area III', acc_area=self.area3,
            uploaded_by=self.admin,
        )

    def _login_faculty(self):
        self.client.login(username='fac_user', password='pass12345')

    # --- Access to pages ---

    def test_faculty_can_access_repository(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:repository'))
        self.assertEqual(r.status_code, 200)

    def test_faculty_can_access_dashboard_and_search(self):
        self._login_faculty()
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 200)
        # The standalone Smart Search page was removed; searching now lives in the
        # Repository. The old URL redirects there and carries the query across, so
        # a faculty member following an old link still lands on a usable search.
        r = self.client.get(reverse('search:search'), {'q': 'annual'})
        self.assertRedirects(r, reverse('documents:repository') + '?q=annual')

    def test_faculty_blocked_from_admin_pages(self):
        self._login_faculty()
        for name in ('accounts:user_list', 'reports:page', 'ai_processing:list'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, f'{name} should be blocked')

    # --- Repository scoping ---

    def test_repository_shows_only_assigned_area(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:repository'))
        body = r.content.decode()
        self.assertIn('Area2 Doc', body)
        self.assertIn('My Own Doc', body)
        self.assertNotIn('Area3 Doc', body)

    # --- Document-level access ---

    def test_faculty_can_view_in_area_document(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:detail', args=[self.doc_area2.pk]))
        self.assertEqual(r.status_code, 200)

    def test_faculty_cannot_view_out_of_area_document(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:detail', args=[self.doc_area3.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)

    def test_faculty_download_out_of_area_is_404(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:download', args=[self.doc_area3.pk]))
        self.assertEqual(r.status_code, 404)

    # --- Edit / delete: own uploads only ---

    def test_faculty_cannot_delete_others_document(self):
        self._login_faculty()
        r = self.client.post(reverse('documents:delete', args=[self.doc_area2.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Document.objects.filter(pk=self.doc_area2.pk).exists())

    def test_faculty_can_delete_own_document(self):
        self._login_faculty()
        r = self.client.post(reverse('documents:delete', args=[self.doc_own.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Document.objects.filter(pk=self.doc_own.pk).exists())

    def test_faculty_cannot_edit_others_document(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:edit', args=[self.doc_area2.pk]))
        self.assertEqual(r.status_code, 302)

    def test_faculty_can_open_own_edit(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:edit', args=[self.doc_own.pk]))
        self.assertEqual(r.status_code, 200)

    # --- Upload page ---

    def test_faculty_upload_page_loads(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:faculty_upload'))
        self.assertEqual(r.status_code, 200)

    def test_faculty_bulk_upload_page_shows_area(self):
        self._login_faculty()
        r = self.client.get(reverse('documents:bulk_upload'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Area II', r.content.decode())

    def test_faculty_bulk_upload_tags_assigned_area(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self._login_faculty()
        f = SimpleUploadedFile('memo_bulk.pdf', b'%PDF-1.4 hello', content_type='application/pdf')
        r = self.client.post(
            reverse('documents:bulk_upload'), {'files': f},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertIn(r.status_code, (200, 302))
        doc = Document.objects.filter(title='memo_bulk').order_by('-pk').first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.qa_area, 'Area II')
        self.assertEqual(doc.acc_area_id, self.area2.pk)
        self.assertEqual(doc.uploaded_by_id, self.faculty.id)

    def test_multi_area_faculty_bulk_requires_area_choice(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        multi = User.objects.create_user('fac_two', 't@test.com', 'pass12345')
        multi.profile.role = 'faculty'
        multi.profile.save()
        multi.profile.assigned_areas.set([self.area2, self.area3])
        self.client.login(username='fac_two', password='pass12345')
        f = SimpleUploadedFile('x.pdf', b'%PDF-1.4', content_type='application/pdf')
        r = self.client.post(
            reverse('documents:bulk_upload'), {'files': f},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 400)

    def test_faculty_upload_form_rejects_unassigned_area(self):
        from documents.forms import FacultyUploadForm
        form = FacultyUploadForm(
            data={'title': 'X', 'year': 2026, 'document_type': 'Report', 'qa_area': 'Area III'},
            allowed_area_codes=['Area II'],
        )
        self.assertFalse(form.is_valid())
        self.assertIn('qa_area', form.errors)


class FacultyNoAreaTests(TestCase):
    """A faculty member with no assigned area sees nothing and cannot upload."""

    def setUp(self):
        self.client = Client()
        self.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area I', defaults={'area_name': 'VMG'})
        self.faculty = User.objects.create_user('fac_empty', 'e@test.com', 'pass12345')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()
        self.doc = Document.objects.create(
            title='Some Doc', file='uploaded_documents/2026/05/s.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area I', acc_area=self.area,
            uploaded_by=self.faculty,
        )

    def test_repository_empty_for_unassigned_faculty(self):
        self.client.login(username='fac_empty', password='pass12345')
        r = self.client.get(reverse('documents:repository'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('Some Doc', r.content.decode())

    def test_upload_redirects_when_no_area_assigned(self):
        self.client.login(username='fac_empty', password='pass12345')
        r = self.client.get(reverse('documents:faculty_upload'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)


class SidebarBadgeTests(TestCase):
    def setUp(self):
        self.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        self.area3, _ = AccreditationArea.objects.get_or_create(
            area_code='Area III', defaults={'area_name': 'Curriculum'})

        self.admin = User.objects.create_user('sb_admin', 'a@test.com', 'pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

        self.faculty = User.objects.create_user('sb_faculty', 'f@test.com', 'pass12345')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()
        self.faculty.profile.assigned_areas.set([self.area2])

        Document.objects.create(
            title='Area2 Doc', file='uploaded_documents/2026/05/a2.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area II', acc_area=self.area2,
            uploaded_by=self.admin,
        )
        Document.objects.create(
            title='Area3 Doc', file='uploaded_documents/2026/05/a3.pdf', file_type='pdf',
            year=2026, document_type='Report', qa_area='Area III', acc_area=self.area3,
            uploaded_by=self.admin,
        )

    def test_sidebar_doc_count_scoped_for_faculty(self):
        from dashboard.context_processors import sidebar_badges
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = self.faculty
        self.assertEqual(sidebar_badges(request)['sidebar_doc_count'], 1)

    def test_sidebar_doc_count_all_for_admin(self):
        from dashboard.context_processors import sidebar_badges
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = self.admin
        self.assertEqual(sidebar_badges(request)['sidebar_doc_count'], 2)

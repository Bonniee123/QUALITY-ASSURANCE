"""Tests for role-based access control."""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.permissions import is_qa_staff_or_admin
from documents.models import ActivityLog, Document


class RBACTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user('rbac_admin', 'admin@test.com', 'pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

        self.qa_head = User.objects.create_user('rbac_qa', 'qa@test.com', 'pass12345')
        self.qa_head.profile.role = 'qa_staff'
        self.qa_head.profile.save()

        self.inactive = User.objects.create_user('rbac_inactive', 'in@test.com', 'pass12345')
        self.inactive.profile.role = 'qa_staff'
        self.inactive.profile.status = 'inactive'
        self.inactive.profile.save()

        self.faculty = User.objects.create_user('rbac_faculty', 'fac@test.com', 'pass12345')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()

        self.doc = Document.objects.create(
            title='RBAC Test Doc',
            file='uploaded_documents/2026/05/rbac.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            uploaded_by=self.admin,
        )

    def test_qa_head_can_access_repository(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('documents:repository'))
        self.assertEqual(r.status_code, 200)

    def test_anonymous_root_redirects_to_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login', r.url)

    def test_anonymous_dashboard_redirects_to_login(self):
        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login', r.url)

    def test_qa_head_blocked_from_reports(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('reports:page'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)

    def test_qa_head_blocked_from_ai_processing(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('ai_processing:list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)

    def test_qa_head_blocked_from_user_management(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(r.status_code, 302)

    def test_admin_can_access_reports_and_ai(self):
        self.client.login(username='rbac_admin', password='pass12345')
        self.assertEqual(self.client.get(reverse('reports:page')).status_code, 200)
        self.assertEqual(self.client.get(reverse('ai_processing:list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:user_list')).status_code, 200)

    def test_qa_head_can_delete_document(self):
        # QA Head consolidates submissions and may remove wrong files sent by faculty.
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.post(reverse('documents:delete', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        # Reversible: out of every listing, still there for ten seconds of undo.
        self.assertFalse(Document.objects.live().filter(pk=self.doc.pk).exists())
        self.assertTrue(Document.objects.deleted().filter(pk=self.doc.pk).exists())

    def test_admin_can_open_delete_confirmation(self):
        self.client.login(username='rbac_admin', password='pass12345')
        r = self.client.get(reverse('documents:delete', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 200)

    def test_inactive_user_blocked_after_login_attempt_via_view(self):
        self.client.login(username='rbac_inactive', password='pass12345')
        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login', r.url)

    def test_permission_denied_is_logged(self):
        self.client.login(username='rbac_qa', password='pass12345')
        self.client.get(reverse('reports:page'))
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.qa_head,
                action='permission_denied',
            ).exists()
        )

    def test_is_qa_staff_or_admin_excludes_faculty(self):
        self.assertTrue(is_qa_staff_or_admin(self.admin))
        self.assertTrue(is_qa_staff_or_admin(self.qa_head))
        self.assertFalse(is_qa_staff_or_admin(self.faculty))

    def test_faculty_blocked_from_area_submissions(self):
        self.client.login(username='rbac_faculty', password='pass12345')
        r = self.client.get(reverse('documents:area_submissions'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)

    def test_faculty_blocked_from_clusters(self):
        self.client.login(username='rbac_faculty', password='pass12345')
        r = self.client.get(reverse('documents:clusters'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)

    def test_qa_head_can_access_area_submissions(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('documents:area_submissions'))
        self.assertEqual(r.status_code, 200)

    def test_qa_head_can_access_clusters(self):
        self.client.login(username='rbac_qa', password='pass12345')
        r = self.client.get(reverse('documents:clusters'))
        self.assertEqual(r.status_code, 200)

    # The accreditation-area management page went with the rest of the
    # accreditation hierarchy: areas are ten fixed reference rows seeded by
    # migration, and the pages that let staff build a five-level structure on top
    # of them were out of scope for an upload-and-review system. What the two
    # tests here actually protected -- that a faculty account cannot reach
    # another area's documents -- is covered by AreaScopeTests below and by
    # documents.tests.test_area_filter.

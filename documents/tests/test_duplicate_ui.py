"""RBAC and UI tests for duplicate review workflow."""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class DuplicateReviewRBACTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )

        self.admin = User.objects.create_user('dup_admin', 'dup-admin@test.com', 'pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

        self.qa_head = User.objects.create_user('dup_qa', 'dup-qa@test.com', 'pass12345')
        self.qa_head.profile.role = 'qa_staff'
        self.qa_head.profile.save()

        self.faculty = User.objects.create_user('dup_faculty', 'dup-fac@test.com', 'pass12345')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()
        self.faculty.profile.assigned_areas.set([self.area2])

        self.doc = Document.objects.create(
            title='Duplicate Review Doc',
            file='uploaded_documents/2026/05/dup-review.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            uploaded_by=self.faculty,
            qa_area='Area II',
            acc_area=self.area2,
            duplicate_status='possible',
        )

    def test_qa_head_can_confirm_duplicate(self):
        self.client.login(username='dup_qa', password='pass12345')
        r = self.client.post(reverse('documents:duplicate_confirm', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'confirmed_dup')

    def test_qa_head_can_dismiss_duplicate(self):
        self.client.login(username='dup_qa', password='pass12345')
        r = self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'none')

    def test_admin_can_confirm_duplicate(self):
        self.client.login(username='dup_admin', password='pass12345')
        r = self.client.post(reverse('documents:duplicate_confirm', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'confirmed_dup')

    def test_faculty_cannot_confirm_duplicate(self):
        self.client.login(username='dup_faculty', password='pass12345')
        r = self.client.post(reverse('documents:duplicate_confirm', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'possible')

    def test_faculty_cannot_dismiss_duplicate(self):
        self.client.login(username='dup_faculty', password='pass12345')
        r = self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/documents/repository', r.url)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'possible')

    def test_qa_head_sees_duplicate_filter(self):
        self.client.login(username='dup_qa', password='pass12345')
        r = self.client.get(reverse('documents:repository'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="duplicate"')
        self.assertContains(r, 'Needs review')

    def test_faculty_duplicate_url_param_is_ignored(self):
        self.client.login(username='dup_faculty', password='pass12345')
        r_normal = self.client.get(reverse('documents:repository'))
        r_dup = self.client.get(reverse('documents:repository'), {'duplicate': 'review'})
        self.assertEqual(r_normal.status_code, 200)
        self.assertEqual(r_dup.status_code, 200)
        self.assertNotContains(r_dup, 'name="duplicate"')
        self.assertEqual(r_normal.content.count(b'doc-row'), r_dup.content.count(b'doc-row'))

    def test_qa_head_repository_filter_by_duplicate_review(self):
        self.client.login(username='dup_qa', password='pass12345')
        r = self.client.get(reverse('documents:repository'), {'duplicate': 'review'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.doc.title)

    def test_detail_panel_shows_review_actions_for_qa_head(self):
        self.client.login(username='dup_qa', password='pass12345')
        r = self.client.get(
            reverse('documents:detail', args=[self.doc.pk]),
            {'panel': '1'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Mark as clear')
        self.assertContains(r, 'Confirm duplicate')

    def test_detail_panel_hides_review_actions_for_faculty(self):
        self.client.login(username='dup_faculty', password='pass12345')
        r = self.client.get(
            reverse('documents:detail', args=[self.doc.pk]),
            {'panel': '1'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Confirm duplicate')
        self.assertNotContains(r, 'Mark as clear')
        # The badge went with the buttons. A Faculty member was shown the
        # verdict "Needs review" on a document they cannot review, next to a
        # Repository column and a Dashboard card that no longer mention
        # duplicates to them at all.
        self.assertNotContains(r, 'Needs review')
        self.assertNotContains(r, 'Duplicate Check')

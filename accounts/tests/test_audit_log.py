"""Tests for admin audit log page and audit helpers."""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from documents.audit import log_activity, action_label
from documents.models import ActivityLog


class AuditLogPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user('audit_admin', 'aa@test.com', 'pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()

        self.qa_head = User.objects.create_user('audit_qa', 'aq@test.com', 'pass12345')
        self.qa_head.profile.role = 'qa_staff'
        self.qa_head.profile.save()

        ActivityLog.objects.create(
            user=self.admin,
            action='login',
            description='audit_admin logged in.',
        )
        ActivityLog.objects.create(
            user=None,
            action='login_failed',
            description='Failed login for username "hacker".',
        )

    def test_admin_can_open_audit_log(self):
        self.client.login(username='audit_admin', password='pass12345')
        r = self.client.get(reverse('accounts:audit_log'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Audit Log')
        self.assertContains(r, 'Failed sign in')

    def test_qa_head_blocked_from_audit_log(self):
        self.client.login(username='audit_qa', password='pass12345')
        r = self.client.get(reverse('accounts:audit_log'))
        self.assertEqual(r.status_code, 302)

    def test_filter_by_action(self):
        self.client.login(username='audit_admin', password='pass12345')
        r = self.client.get(reverse('accounts:audit_log'), {'action': 'login_failed'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Failed sign in')
        self.assertNotContains(r, 'audit_admin logged in')

    def test_filter_by_search_query(self):
        self.client.login(username='audit_admin', password='pass12345')
        r = self.client.get(reverse('accounts:audit_log'), {'q': 'hacker'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'hacker')


class AuditHelperTests(TestCase):
    def test_action_label_humanizes_unknown_codes(self):
        self.assertEqual(action_label('export_report'), 'Report exported')
        self.assertEqual(action_label('custom_event'), 'Custom Event')

    def test_log_activity_stores_entry(self):
        actor = User.objects.create_user('log_user', 'l@test.com', 'pass12345')
        log_activity(None, 'search', 'Smart search: policy.', user=actor)
        self.assertTrue(ActivityLog.objects.filter(action='search', user=actor).exists())

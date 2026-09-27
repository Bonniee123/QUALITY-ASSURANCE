"""Tests for authentication security (rate limiting, session, audit)."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from documents.models import ActivityLog


@override_settings(
    LOGIN_RATE_LIMIT_ATTEMPTS=3,
    LOGIN_RATE_LIMIT_WINDOW=900,
    LOGIN_RATE_LIMIT_LOCKOUT=900,
    SESSION_IDLE_TIMEOUT=0,
)
class AuthenticationSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user('auth_user', 'auth@test.com', 'correct-pass')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()

    def test_failed_login_is_logged(self):
        self.client.post(reverse('accounts:login'), {
            'username': 'auth_user',
            'password': 'wrong-pass',
        })
        self.assertTrue(
            ActivityLog.objects.filter(action='login_failed').exists()
        )

    def test_successful_login_is_logged_with_ip(self):
        self.client.post(reverse('accounts:login'), {
            'username': 'auth_user',
            'password': 'correct-pass',
        })
        log = ActivityLog.objects.filter(action='login', user=self.user).first()
        self.assertIsNotNone(log)
        self.assertIn('logged in', log.description)
        self.assertIn('IP', log.description)

    def test_login_lockout_after_max_failures(self):
        url = reverse('accounts:login')
        for _ in range(3):
            self.client.post(url, {'username': 'auth_user', 'password': 'wrong-pass'})

        r = self.client.post(url, {'username': 'auth_user', 'password': 'correct-pass'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Too many failed login attempts')

    def test_successful_login_clears_lockout_counters(self):
        url = reverse('accounts:login')
        for _ in range(2):
            self.client.post(url, {'username': 'auth_user', 'password': 'wrong-pass'})

        r = self.client.post(url, {'username': 'auth_user', 'password': 'correct-pass'})
        self.assertEqual(r.status_code, 302)

        self.client.logout()
        r2 = self.client.post(url, {'username': 'auth_user', 'password': 'wrong-pass'})
        self.assertEqual(r2.status_code, 200)
        self.assertNotContains(r2, 'Too many failed login attempts')

    def test_login_honors_next_parameter(self):
        r = self.client.post(
            reverse('accounts:login') + '?next=/documents/repository/',
            {'username': 'auth_user', 'password': 'correct-pass'},
        )
        self.assertRedirects(r, '/documents/repository/', fetch_redirect_response=False)


@override_settings(SESSION_IDLE_TIMEOUT=60)
class SessionIdleTimeoutTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('idle_user', 'idle@test.com', 'pass12345')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()
        self.client.login(username='idle_user', password='pass12345')

    def test_idle_session_logs_out(self):
        session = self.client.session
        session['_auth_last_activity'] = 0
        session.save()

        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login', r.url)

"""
The offline page, the service worker that serves it, and the health check the
reconnect logic asks.

All three are reached by people who may have been signed out and by a browser
with no connection, so none may need a session, and the worker must only ever
step in for page loads that failed.
"""
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import Client, TestCase


class OfflinePageTests(TestCase):

    def test_the_offline_page_needs_no_sign_in(self):
        response = Client().get('/offline/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You're offline")
        self.assertContains(response, 'data-offline-retry')
        self.assertContains(response, 'qaReconnect')

    def test_it_depends_on_no_other_file(self):
        """Served with no connection, so styles, script and picture are all inline."""
        html = Client().get('/offline/').content.decode()
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<img', html)

    def test_the_health_check_is_tiny_and_uncached(self):
        response = Client().get('/healthz/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.assertIn('no-cache', response.get('Cache-Control', ''))

    def test_the_service_worker_covers_the_whole_site(self):
        response = Client().get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/javascript'))
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        body = response.content.decode()
        self.assertIn("request.mode !== 'navigate'", body)
        self.assertIn("request.method !== 'GET'", body)
        self.assertIn("'/offline/'", body)

    def test_every_signed_in_page_carries_the_overlay(self):
        user = User.objects.create_user('offline_fac', 'o@test.com', 'pass12345')
        user.profile.role = 'faculty'
        user.profile.save()
        client = Client()
        client.force_login(user)
        page = client.get('/documents/repository/')
        self.assertContains(page, 'id="qaOfflineOverlay"')
        self.assertContains(page, 'data-offline-dismiss')
        self.assertContains(page, 'js/connection.js')


class StatusPageDesignTests(TestCase):
    """400, 403, 404, 500, the expired-form page and the offline page: one design."""

    PAGES = ('400.html', '403.html', '403_csrf.html', '404.html', '500.html', 'offline.html')

    def test_every_status_page_uses_the_shared_card_and_buttons(self):
        for name in self.PAGES:
            with self.subTest(page=name):
                html = render_to_string(name)
                self.assertIn('class="err-card"', html)
                self.assertIn('class="err-art"', html)
                self.assertIn('class="err-btn', html)
                self.assertIn('.err-btn.is-secondary', html)

    def test_no_page_keeps_its_own_copy_of_the_styles(self):
        for name in self.PAGES:
            with self.subTest(page=name):
                html = render_to_string(name)
                self.assertEqual(html.count('--err-ink: #0F172A'), 1)

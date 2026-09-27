"""
The app's own error pages are shown in every mode (qa_archiving_system.error_pages).

With DEBUG on -- the default on the laptop -- a mistyped address used to show
Django's technical page, listing every URL pattern, and a crash showed the
traceback and settings. None of the pages shows an error code any more.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings

TECHNICAL_MARKERS = ('URLconf', 'Traceback', 'Django tried these URL patterns', 'CSRF verification failed',
                     'Invalid HTTP_HOST header', 'boom')
ERROR_CODES = ('Error 400', 'Error 403', 'Error 404', 'Error 500', '403 Forbidden')


class FriendlyPageAssertions:
    def assertFriendly(self, response, status, heading):
        self.assertEqual(response.status_code, status)
        text = response.content.decode()
        self.assertIn(heading, text)
        for marker in TECHNICAL_MARKERS + ERROR_CODES:
            self.assertNotIn(marker, text)


@override_settings(DEBUG=True, SHOW_DEBUG_ERROR_PAGES=False)
class DebugModeErrorPageTests(FriendlyPageAssertions, TestCase):

    def test_an_unknown_address_shows_the_friendly_404(self):
        r = Client().get('/no-such-page/')
        self.assertFriendly(r, 404, 'Page not found')
        self.assertTemplateNotUsed(r, 'technical_404.html')

    def test_a_missing_record_shows_the_friendly_404(self):
        user = User.objects.create_user('err_admin', password='pass12345')
        user.profile.role = 'admin'
        user.profile.save()
        client = Client()
        client.force_login(user)
        self.assertFriendly(client.get('/documents/99999999/'), 404, 'Page not found')

    def test_a_crash_shows_the_friendly_500_and_still_logs_the_traceback(self):
        with mock.patch('accounts.views.redirect', side_effect=RuntimeError('boom')):
            with self.assertLogs('django.request', level='ERROR') as logs:
                r = Client(raise_request_exception=False).get('/')
        self.assertFriendly(r, 500, 'Something went wrong')
        self.assertIn('boom', '\n'.join(logs.output))

    def test_a_crash_answers_a_script_with_plain_text_and_no_traceback(self):
        with mock.patch('accounts.views.redirect', side_effect=RuntimeError('boom')):
            with self.assertLogs('django.request', level='ERROR'):
                r = Client(raise_request_exception=False).get('/', HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.content.decode(), 'Something went wrong. Please try again in a moment.')

    def test_a_refused_permission_shows_the_friendly_403(self):
        with mock.patch('accounts.views.redirect', side_effect=PermissionDenied):
            r = Client().get('/')
        self.assertFriendly(r, 403, 'Access denied')

    def test_an_expired_form_shows_the_friendly_page(self):
        r = Client(enforce_csrf_checks=True).post('/accounts/login/', {'username': 'x', 'password': 'y'})
        self.assertFriendly(r, 403, 'This page has expired')

    def test_a_bad_host_shows_the_friendly_400(self):
        r = Client().get('/accounts/login/', HTTP_HOST='evil.example')
        self.assertFriendly(r, 400, "We couldn't process that request")

    def test_the_security_headers_are_kept(self):
        r = Client().get('/no-such-page/')
        self.assertIn("default-src 'self'", r.get('Content-Security-Policy', ''))
        self.assertEqual(r.get('X-Content-Type-Options'), 'nosniff')

    def test_a_missing_trailing_slash_is_still_redirected(self):
        r = Client().get('/accounts/login')
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.url, '/accounts/login/')

    def test_normal_pages_are_untouched(self):
        r = Client().get('/accounts/login/')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'accounts/login.html')


@override_settings(DEBUG=True, SHOW_DEBUG_ERROR_PAGES=True)
class DeveloperSwitchTests(TestCase):

    def test_the_switch_brings_back_djangos_technical_page(self):
        r = Client().get('/no-such-page/')
        self.assertEqual(r.status_code, 404)
        self.assertIn(b'URLconf', r.content)


@override_settings(DEBUG=False)
class ProductionModeErrorPageTests(FriendlyPageAssertions, TestCase):

    def test_an_unknown_address_shows_the_friendly_404(self):
        self.assertFriendly(Client().get('/no-such-page/'), 404, 'Page not found')

    def test_a_crash_shows_the_friendly_500(self):
        with mock.patch('accounts.views.redirect', side_effect=RuntimeError('boom')):
            with self.assertLogs('django.request', level='ERROR'):
                r = Client(raise_request_exception=False).get('/')
        self.assertFriendly(r, 500, 'Something went wrong')

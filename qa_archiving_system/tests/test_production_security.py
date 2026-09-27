"""Tests for production security middleware and settings."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings


@override_settings(DEBUG=False, MEDIA_URL='/media/')
class BlockPublicMediaMiddlewareTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_media_url_returns_403_when_not_debug(self):
        r = self.client.get('/media/uploaded_documents/test.pdf')
        self.assertEqual(r.status_code, 403)
        self.assertIn(b'Direct access', r.content)


@override_settings(DEBUG=True, MEDIA_URL='/media/')
class BlockPublicMediaDevTests(TestCase):
    """DEBUG is on by default on the laptop, and uploads must stay private there too."""

    def assertBlocked(self, path):
        r = Client().get(path)
        self.assertEqual(r.status_code, 403, path)
        self.assertIn(b'Direct access', r.content)

    def test_uploaded_documents_are_blocked_in_debug_too(self):
        self.assertBlocked('/media/uploaded_documents/test.pdf')
        self.assertBlocked('/media/preview_cache/doc_1_abc.pdf')

    def test_signed_in_users_are_blocked_too(self):
        user = User.objects.create_user('media_admin', password='pass12345')
        user.profile.role = 'admin'
        user.profile.save()
        client = Client()
        client.force_login(user)
        r = client.get('/media/uploaded_documents/test.pdf')
        self.assertEqual(r.status_code, 403)

    def test_profile_pictures_are_not_blocked(self):
        r = Client().get('/media/profile_pics/2026/09/missing.jpg')
        self.assertNotEqual(r.status_code, 403)

    def test_the_photo_folder_cannot_be_used_to_reach_documents(self):
        self.assertBlocked('/media/profile_pics/../uploaded_documents/test.pdf')
        self.assertBlocked('/media/profile_pics/%2e%2e/uploaded_documents/test.pdf')
        self.assertBlocked('/media/profile_pics/..\\uploaded_documents\\test.pdf')
        self.assertBlocked('/media//uploaded_documents/test.pdf')


class AdminLoginRedirectTests(TestCase):
    """Django admin's own sign-in page had no lockout; it now uses the app's."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_admin_login_goes_to_the_app_login(self):
        r = Client().get('/admin/login/?next=/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/accounts/login/?next=/admin/')

    def test_signed_out_visit_to_admin_ends_on_the_app_login(self):
        from urllib.parse import parse_qs, urlsplit

        r = Client().get('/admin/', follow=True)
        self.assertEqual(r.status_code, 200)
        last = urlsplit(r.redirect_chain[-1][0])
        self.assertEqual(last.path, '/accounts/login/')
        self.assertEqual(parse_qs(last.query)['next'], ['/admin/'])
        self.assertTemplateUsed(r, 'accounts/login.html')

    def test_superuser_signs_in_and_returns_to_admin(self):
        User.objects.create_superuser('root_admin', 'root@test.com', 'pass12345')
        client = Client()
        r = client.post('/accounts/login/?next=/admin/',
                        {'username': 'root_admin', 'password': 'pass12345', 'next': '/admin/'})
        self.assertRedirects(r, '/admin/', fetch_redirect_response=False)
        self.assertEqual(client.get('/admin/').status_code, 200)

    def test_signed_in_non_staff_user_is_not_sent_round_in_circles(self):
        user = User.objects.create_user('plain_head', password='pass12345')
        user.profile.role = 'qa_staff'
        user.profile.save()
        client = Client()
        client.force_login(user)
        r = client.get('/admin/', follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertLess(len(r.redirect_chain), 5)
        self.assertEqual(r.redirect_chain[-1][0], '/dashboard/')


class SecurityHeadersTests(TestCase):
    """Defense-in-depth headers added by SecurityHeadersMiddleware."""

    def setUp(self):
        self.client = Client()

    def test_csp_header_present_and_locked_down(self):
        r = self.client.get('/accounts/login/')
        csp = r.get('Content-Security-Policy', '')
        self.assertIn("default-src 'self'", csp)
        # object-src is restricted to our own origin + blob: (for the PDF
        # preview embed); external plugins are still blocked.
        self.assertIn("object-src 'self' blob:", csp)
        self.assertNotIn('object-src *', csp)
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertIn("base-uri 'self'", csp)

    def test_nosniff_and_permissions_policy_present(self):
        r = self.client.get('/accounts/login/')
        self.assertEqual(r.get('X-Content-Type-Options'), 'nosniff')
        self.assertIn('camera=()', r.get('Permissions-Policy', ''))

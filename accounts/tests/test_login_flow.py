"""
The sign-in flow: one path, decided by the server, the same for every role.

    Login -> Authentication -> Successful Login -> Redirect to the dashboard

The page's own script defers to the server whenever it is unsure (brought back
from the browser's cache, or still waiting after submitting), so what these
pin down is the server behaviour it relies on -- plus the two hooks that let a
sign-in page left open in another tab follow a sign-in instead of sitting on
"Signing in".
"""
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.views import login_view

PASSWORD = 'testpass123'
ROLES = (('flow_faculty', 'faculty'), ('flow_qa', 'qa_staff'), ('flow_admin', 'admin'))


def make_user(username, role):
    user = User.objects.create_user(username, f'{username}@e.com', PASSWORD)
    user.profile.role = role
    user.profile.save()
    return user


class SignInLandsOnTheDashboardTests(TestCase):
    """Every role signs in the same way and arrives in one place."""

    def setUp(self):
        for username, role in ROLES:
            make_user(username, role)

    def test_each_role_is_redirected_to_its_dashboard(self):
        for username, role in ROLES:
            with self.subTest(role=role):
                client = self.client_class()
                response = client.post(reverse('accounts:login'),
                                       {'username': username, 'password': PASSWORD})
                self.assertRedirects(response, reverse('dashboard:home'))

    def test_one_redirect_and_the_page_loads(self):
        """A single redirect, and the page at the end of it renders."""
        for username, role in ROLES:
            with self.subTest(role=role):
                client = self.client_class()
                response = client.post(reverse('accounts:login'),
                                       {'username': username, 'password': PASSWORD}, follow=True)
                self.assertEqual(len(response.redirect_chain), 1)
                self.assertEqual(response.status_code, 200)

    def test_a_wrong_password_stays_on_the_page_with_an_error(self):
        response = self.client.post(reverse('accounts:login'),
                                    {'username': 'flow_faculty', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_offsite_next_is_ignored(self):
        response = self.client.post(reverse('accounts:login') + '?next=//evil.example/',
                                    {'username': 'flow_faculty', 'password': PASSWORD})
        self.assertRedirects(response, reverse('dashboard:home'))


class TheServerIsTheSourceOfTruthTests(TestCase):
    """What the sign-in page asks when it is unsure, and what it gets back."""

    def setUp(self):
        for username, role in ROLES:
            make_user(username, role)

    def test_a_signed_in_visitor_is_sent_on_from_the_login_page(self):
        """The page's check is a no-redirect fetch of this URL: 302 means signed in."""
        for username, role in ROLES:
            with self.subTest(role=role):
                client = self.client_class()
                client.login(username=username, password=PASSWORD)
                response = client.get(reverse('accounts:login'))
                self.assertRedirects(response, reverse('dashboard:home'))

    def test_a_signed_out_visitor_gets_the_form(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)

    def test_the_login_page_is_never_cached(self):
        """
        A cached copy is what Back shows after signing in: greyed out on
        "Signing in", with no request made that could redirect.
        """
        response = self.client.get(reverse('accounts:login'))
        cache_control = response.get('Cache-Control', '')
        self.assertIn('no-store', cache_control)
        self.assertIn('no-cache', cache_control)

    def test_the_password_is_kept_out_of_error_reports(self):
        request = RequestFactory().post(reverse('accounts:login'),
                                        {'username': 'nobody', 'password': 'x'})
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        request.user = AnonymousUser()
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        login_view(request)
        self.assertEqual(request.sensitive_post_parameters, ('password',))


class OtherTabsFollowTheSignInTests(TestCase):
    """The two halves of the cross-tab hand-off."""

    def setUp(self):
        make_user('flow_faculty', 'faculty')

    def test_signed_in_pages_announce_the_sign_in(self):
        self.client.login(username='flow_faculty', password=PASSWORD)
        response = self.client.get(reverse('dashboard:home'))
        self.assertContains(response, "localStorage.setItem('qaAuthState'")

    def test_the_login_page_listens_but_does_not_announce(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, "e.key === 'qaAuthState'")
        self.assertNotContains(response, "localStorage.setItem('qaAuthState'")

    def test_the_login_page_keeps_submission_in_this_tab(self):
        """Modified clicks are turned back into an ordinary same-tab submit."""
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'e.ctrlKey || e.metaKey || e.shiftKey')
        self.assertContains(response, 'form.requestSubmit(btn)')
        self.assertNotContains(response, 'window.open')

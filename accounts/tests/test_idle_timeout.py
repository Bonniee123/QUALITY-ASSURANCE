"""
The one-hour idle sign-out, now that it can actually fire.

Every signed-in page refreshes its badges every five seconds, and those requests
used to reset the idle clock -- so the hour never ran out while a tab was open,
and a screen left signed in stayed signed in. The page now marks its automatic
requests passive once nobody has touched it for a minute; only real use resets
the clock.
"""
import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

PASSWORD = 'testpass123'
HOUR = 60 * 60
PASSIVE = {'HTTP_X_QA_PASSIVE': '1'}
BADGE_POLL = '/messages/sync/?counts=1'


class IdleClockTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('idle_fac', 'i@e.com', PASSWORD)
        self.user.profile.role = 'faculty'
        self.user.profile.save()
        self.client.login(username='idle_fac', password=PASSWORD)

    def set_last_activity(self, seconds_ago):
        session = self.client.session
        session['_auth_last_activity'] = time.time() - seconds_ago
        session.save()
        return session['_auth_last_activity']

    def last_activity(self):
        return self.client.session.get('_auth_last_activity')

    # ---------------------------------------------------------------- the clock

    def test_an_automatic_refresh_nobody_asked_for_does_not_reset_it(self):
        before = self.set_last_activity(30 * 60)
        response = self.client.get(BADGE_POLL, **PASSIVE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.last_activity(), before)

    def test_real_use_resets_it(self):
        before = self.set_last_activity(30 * 60)
        self.client.get(reverse('dashboard:home'))
        self.assertGreater(self.last_activity(), before)

    def test_a_refresh_while_someone_is_using_the_page_still_counts(self):
        """Not passive -- the person is at the page -- so it keeps them signed in."""
        before = self.set_last_activity(30 * 60)
        self.client.get(BADGE_POLL)
        self.assertGreater(self.last_activity(), before)

    def test_an_open_tab_nobody_uses_is_signed_out_after_the_hour(self):
        """
        The failure this fixes: five-second refreshes used to keep this session
        alive forever. Now they run out the clock like any other idle time.
        """
        self.set_last_activity(30 * 60)
        for _ in range(3):                          # refreshes while unattended...
            self.assertEqual(self.client.get(BADGE_POLL, **PASSIVE).status_code, 200)
        self.set_last_activity(HOUR + 60)          # ...until the hour is up
        response = self.client.get(BADGE_POLL, **PASSIVE)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    # -------------------------------------------------- what an expiry looks like

    def test_a_background_request_gets_a_401_the_page_can_act_on(self):
        """fetch() would silently follow a redirect; a 401 lets the page go to sign-in."""
        self.set_last_activity(HOUR + 60)
        response = self.client.get(BADGE_POLL, **PASSIVE)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'session_expired': True})
        self.assertEqual(response['X-QA-Login'], reverse('accounts:login'))

    def test_an_ajax_request_gets_the_same_401(self):
        self.set_last_activity(HOUR + 60)
        response = self.client.get(reverse('documents:upload_batches'),
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 401)

    def test_a_page_request_is_still_redirected_to_sign_in(self):
        self.set_last_activity(HOUR + 60)
        response = self.client.get(reverse('dashboard:home'))
        self.assertRedirects(response, reverse('accounts:login'), fetch_redirect_response=False)

    def test_the_sign_in_page_says_why(self):
        self.set_last_activity(HOUR + 60)
        self.client.get(BADGE_POLL, **PASSIVE)
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'Your session expired due to inactivity')

    def test_just_under_the_hour_is_still_signed_in(self):
        self.set_last_activity(HOUR - 60)
        self.assertEqual(self.client.get(BADGE_POLL, **PASSIVE).status_code, 200)
        self.assertIn('_auth_user_id', self.client.session)


class PagesMarkTheirOwnRefreshesTests(TestCase):
    """Every automatic poller goes through the shared activity helper."""

    def setUp(self):
        user = User.objects.create_user('idle_qa', 'q@e.com', PASSWORD)
        user.profile.role = 'qa_staff'
        user.profile.save()
        self.client.login(username='idle_qa', password=PASSWORD)

    def static_text(self, path):
        from django.contrib.staticfiles import finders
        with open(finders.find(path), encoding='utf-8') as fh:
            return fh.read()

    def test_the_activity_helper_exists_before_any_poller(self):
        main = self.static_text('js/main.js')
        self.assertIn('window.qaActivity', main)
        self.assertIn("'X-QA-Passive'", main)

    def test_the_badge_and_job_pollers_use_it(self):
        for path in ('js/realtime.js', 'js/job-status.js'):
            with self.subTest(path=path):
                text = self.static_text(path)
                self.assertIn('qa.headers(', text)
                self.assertIn('qa.expired(', text)

    def test_the_upload_and_messages_pages_use_it(self):
        for url in (reverse('documents:bulk_upload'), reverse('messaging:inbox')):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'qaActivity')


class KeepMeSignedInRemovedTests(TestCase):
    """The checkbox promised something the server never did; it is gone."""

    def test_the_login_page_no_longer_offers_it(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertNotContains(response, 'Keep me signed in')
        self.assertNotContains(response, 'name="remember"')
        # The "Need help?" line that used to share this row is gone as well.
        self.assertNotContains(response, 'Need help?')

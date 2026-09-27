"""
User Management's Status column shows who is online, and keeps it current.

It used to show only whether an account was switched on ("Active"), which the
Access switch already says. It now shows Online while the person has the system
open, Offline with when they were last seen, Never signed in, or Inactive for an
account that is switched off; the page refreshes it every 15 seconds.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from accounts.presence import presence


def make_user(username, role='faculty'):
    user = User.objects.create_user(username, f'{username}@e.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    return user


def set_presence(user, **fields):
    UserProfile.objects.filter(user=user).update(**fields)
    user.refresh_from_db()
    user.profile.refresh_from_db()


class PresenceTests(TestCase):

    def setUp(self):
        self.user = make_user('presence_fac')
        self.now = timezone.now()

    def test_never_signed_in(self):
        self.assertEqual(presence(self.user, self.now)['label'], 'Never signed in')

    def test_seen_within_three_minutes_is_online(self):
        set_presence(self.user, last_seen=self.now - timedelta(minutes=2))
        self.assertEqual(presence(self.user, self.now)['state'], 'online')

    def test_seen_longer_ago_is_offline_with_when(self):
        set_presence(self.user, last_seen=self.now - timedelta(minutes=40))
        p = presence(self.user, self.now)
        self.assertEqual(p['state'], 'offline')
        self.assertEqual(p['label'], 'Last seen 40\xa0minutes ago')

    def test_signing_out_is_offline_at_once(self):
        set_presence(self.user, last_seen=self.now - timedelta(seconds=20),
                     last_logout=self.now - timedelta(seconds=5))
        self.assertEqual(presence(self.user, self.now)['label'], 'Last seen just now')

    def test_a_switched_off_account_is_inactive(self):
        set_presence(self.user, last_seen=self.now, status='inactive')
        self.assertEqual(presence(self.user, self.now)['state'], 'inactive')


class PresenceRecordingTests(TestCase):

    def setUp(self):
        self.admin = make_user('presence_admin', 'admin')
        self.faculty = make_user('presence_fac2')

    def seen(self, user):
        return UserProfile.objects.get(user=user).last_seen

    def test_using_the_system_marks_the_user_online(self):
        self.client.force_login(self.faculty)
        self.client.get(reverse('documents:repository'))
        self.assertIsNotNone(self.seen(self.faculty))

    def test_it_writes_at_most_every_thirty_seconds(self):
        self.client.force_login(self.faculty)
        self.client.get(reverse('documents:repository'))
        first = self.seen(self.faculty)
        self.client.get(reverse('documents:repository'))
        self.assertEqual(self.seen(self.faculty), first)
        later = timezone.now() + timedelta(seconds=31)
        with mock.patch('accounts.presence.timezone.now', return_value=later):
            self.client.get(reverse('documents:repository'))
        self.assertEqual(self.seen(self.faculty), later)

    def test_signing_out_is_recorded(self):
        self.client.force_login(self.faculty)
        self.client.post(reverse('accounts:logout'))
        self.assertIsNotNone(UserProfile.objects.get(user=self.faculty).last_logout)

    def test_user_management_shows_presence_and_the_endpoint_is_admin_only(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:user_list')).content.decode()
        self.assertIn('Never signed in', page)
        self.assertIn('status-online', page, "the administrator's own row")
        data = self.client.get(reverse('accounts:user_presence')).json()['users']
        self.assertEqual(data[str(self.admin.pk)]['state'], 'online')
        self.assertEqual(data[str(self.faculty.pk)]['state'], 'never')

        self.client.force_login(self.faculty)
        response = self.client.get(reverse('accounts:user_presence'))
        self.assertNotEqual(response.status_code, 200)


class EarlierSignInTests(TestCase):

    def test_an_account_seen_before_presence_existed_shows_its_last_sign_in(self):
        user = make_user('presence_old')
        User.objects.filter(pk=user.pk).update(last_login=timezone.now() - timedelta(days=2))
        user.refresh_from_db()
        self.assertEqual(presence(user)['label'], 'Last seen 2\xa0days ago')

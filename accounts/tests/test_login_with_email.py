"""
Signing in with an email address (S-AUTH-03).

Accounts are created with both a username and an email address, and people type
whichever one they remember. Only the username worked, and the page said
nothing about which of the two it wanted, so a correct password looked wrong.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse


class LoginWithEmailTests(TestCase):

    def setUp(self):
        # Failed sign-ins are rate limited per IP address in the cache, which
        # outlives a test. Several tests here sign in wrongly on purpose, and
        # without this they lock the address out for every test that follows,
        # in this module and in every module that runs after it.
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user('email_login_user', 'Person@Example.com', 'pass12345')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()
        self.url = reverse('accounts:login')

    def sign_in(self, identifier, password='pass12345'):
        return self.client.post(self.url, {'username': identifier, 'password': password})

    def assert_signed_in(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))

    def test_username_still_works(self):
        self.assert_signed_in(self.sign_in('email_login_user'))

    def test_email_works(self):
        self.assert_signed_in(self.sign_in('Person@Example.com'))

    def test_email_is_matched_whatever_the_case(self):
        self.assert_signed_in(self.sign_in('person@example.com'))

    def test_surrounding_spaces_are_ignored(self):
        self.assert_signed_in(self.sign_in('  person@example.com  '))

    def test_a_wrong_password_is_still_refused(self):
        response = self.sign_in('person@example.com', password='not-the-password')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_an_unknown_email_is_refused(self):
        response = self.sign_in('nobody@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_a_shared_email_signs_nobody_in(self):
        """
        Two accounts, one address: refuse rather than pick one.

        Nothing stops an administrator entering the same address twice, and
        guessing which of the two people is at the keyboard would hand one of
        them the other's session.
        """
        User.objects.create_user('second_owner', 'Person@Example.com', 'pass12345')
        response = self.sign_in('person@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_a_deactivated_account_is_told_so_when_it_uses_its_email(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        response = self.sign_in('person@example.com')
        self.assertContains(response, 'deactivated')

    def test_the_field_says_both_are_accepted(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'Username or email')

"""
Sign-out is a POST (S-SEC-07) and the post-login redirect uses Django's own
host check (S-SEC-01).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LogoutTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('sec_user', password='pass12345')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_loading_the_url_does_not_sign_you_out(self):
        response = self.client.get(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('dashboard:home'))
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 200, 'still signed in')

    def test_the_log_out_button_posts_and_signs_you_out(self):
        page = self.client.get(reverse('dashboard:home')).content.decode()
        self.assertIn(f'<form method="post" action="{reverse("accounts:logout")}"', page)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 302, 'signed out')

    def test_a_cross_site_post_without_the_token_is_refused(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse('accounts:logout')).status_code, 403)


class NextRedirectTests(TestCase):

    def setUp(self):
        User.objects.create_user('next_user', password='pass12345')

    def login(self, next_url):
        return self.client.post(reverse('accounts:login') + f'?next={next_url}',
                                {'username': 'next_user', 'password': 'pass12345'})

    def test_a_path_on_this_site_is_followed(self):
        self.assertEqual(self.login('/documents/repository/')['Location'], '/documents/repository/')

    def test_other_hosts_are_not(self):
        for target in ('//evil.example/', '/\\evil.example', 'https://evil.example/', '/%5Cevil.example'):
            location = self.login(target)['Location']
            self.assertEqual(location, reverse('dashboard:home'), target)

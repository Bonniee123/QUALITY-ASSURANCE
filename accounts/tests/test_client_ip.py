"""
The client IP behind the login lockout, the rate limits and the audit log.

X-Forwarded-For used to be trusted from anyone, so a client could send a new
made-up address with every failed login and never hit the per-IP lock.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.auth_security import get_client_ip


class GetClientIpTests(SimpleTestCase):

    def request(self, forwarded=None):
        extra = {'REMOTE_ADDR': '192.168.1.20'}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return RequestFactory().get('/', **extra)

    def test_the_header_is_ignored_by_default(self):
        self.assertEqual(get_client_ip(self.request('1.2.3.4')), '192.168.1.20')

    @override_settings(TRUST_X_FORWARDED_FOR=True)
    def test_behind_a_trusted_proxy_the_proxy_entry_is_used(self):
        # nginx appends the address it saw to whatever the client sent.
        self.assertEqual(get_client_ip(self.request('1.2.3.4, 203.0.113.9')), '203.0.113.9')
        self.assertEqual(get_client_ip(self.request('203.0.113.9')), '203.0.113.9')

    @override_settings(TRUST_X_FORWARDED_FOR=True)
    def test_an_empty_header_falls_back_to_the_connection(self):
        self.assertEqual(get_client_ip(self.request(' , ')), '192.168.1.20')
        self.assertEqual(get_client_ip(self.request()), '192.168.1.20')


@override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=3, LOGIN_RATE_LIMIT_WINDOW=900, LOGIN_RATE_LIMIT_LOCKOUT=900)
class FakeHeaderLockoutTests(TestCase):

    def setUp(self):
        cache.clear()
        User.objects.create_user('ip_user', password='correct-pass')

    def tearDown(self):
        # The lock lives in the shared cache, not the test database: left behind,
        # it locks every later test that signs in from the same address.
        cache.clear()

    def test_rotating_fake_addresses_still_lock_the_real_one(self):
        url = reverse('accounts:login')
        client = Client()
        # A different username each time, so only the per-IP counter can lock.
        for i in range(3):
            client.post(url, {'username': f'guess{i}', 'password': 'wrong'},
                        HTTP_X_FORWARDED_FOR=f'10.9.9.{i}')
        r = client.post(url, {'username': 'ip_user', 'password': 'correct-pass'},
                        HTTP_X_FORWARDED_FOR='10.9.9.99')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Too many failed login attempts')

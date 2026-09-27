"""
Per-account, per-device limits on the heavy actions: QA Assistant messages,
upload batches and ZIP downloads (qa_archiving_system.rate_limit).
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from documents.models import ActivityLog
from qa_archiving_system import rate_limit


def make_user(username, role='qa_staff'):
    user = User.objects.create_user(username, password='pass12345')
    user.profile.role = role
    user.profile.save()
    return user


class RateLimitTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user('rl_head')
        self.client = Client()
        self.client.force_login(self.user)

    def tearDown(self):
        # Counters live in the shared cache, not the test database, and user ids are
        # reused between tests: left behind, they would count against later tests.
        cache.clear()


@override_settings(CHATBOT_RATE_LIMIT=2, CHATBOT_RATE_LIMIT_WINDOW=60)
class ChatbotRateLimitTests(RateLimitTestCase):

    def ask(self, client=None, **extra):
        return (client or self.client).post(
            '/chatbot/api/', json.dumps({'message': 'How many documents are there?'}),
            content_type='application/json', **extra)

    def test_the_message_past_the_limit_is_refused_with_a_readable_answer(self):
        self.assertEqual(self.ask().status_code, 200)
        self.assertEqual(self.ask().status_code, 200)
        r = self.ask()
        self.assertEqual(r.status_code, 429)
        self.assertIn('too quickly', r.json()['answer'])
        self.assertEqual(r.json()['error'], 'rate_limited')

    def test_a_refusal_is_audited_once_per_window_under_access_denied(self):
        for _ in range(6):
            self.ask()
        self.assertEqual(ActivityLog.objects.filter(
            action='permission_denied', user=self.user,
            description__contains='Too many QA Assistant messages').count(), 1)

    def test_a_refused_message_is_not_stored_in_a_thread(self):
        self.ask()
        self.ask()
        r = self.client.post('/chatbot/api/', json.dumps({
            'message': 'one more', 'start_conversation': True}), content_type='application/json')
        self.assertEqual(r.status_code, 429)
        from chatbot.models import Conversation
        self.assertFalse(Conversation.objects.filter(user=self.user).exists())

    def test_another_account_keeps_its_own_allowance(self):
        for _ in range(3):
            self.ask()
        other = Client()
        other.force_login(make_user('rl_other'))
        self.assertEqual(self.ask(client=other).status_code, 200)

    def test_the_same_account_on_another_device_keeps_its_own_allowance(self):
        for _ in range(3):
            self.ask()
        self.assertEqual(self.ask(REMOTE_ADDR='10.0.0.2').status_code, 200)

    @override_settings(CHATBOT_RATE_LIMIT=0)
    def test_zero_turns_the_limit_off(self):
        for _ in range(5):
            self.assertEqual(self.ask().status_code, 200)


@override_settings(UPLOAD_RATE_LIMIT=2, UPLOAD_RATE_LIMIT_WINDOW=600)
class UploadRateLimitTests(RateLimitTestCase):

    def post(self, **headers):
        # An empty batch still counts; nothing is saved.
        return self.client.post(reverse('documents:bulk_upload'), {}, **headers)

    def test_the_upload_page_gets_json_it_already_displays(self):
        xhr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest', 'HTTP_ACCEPT': 'application/json'}
        self.assertEqual(self.post(**xhr).status_code, 400)  # "No files selected."
        self.assertEqual(self.post(**xhr).status_code, 400)
        r = self.post(**xhr)
        self.assertEqual(r.status_code, 429)
        self.assertFalse(r.json()['ok'])
        self.assertIn('Too many upload batches', r.json()['error'])

    def test_a_plain_form_post_gets_a_message(self):
        self.post()
        self.post()
        r = self.post()
        self.assertRedirects(r, reverse('documents:bulk_upload'), fetch_redirect_response=False)
        texts = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any('Too many upload batches' in t for t in texts), texts)

    def test_opening_the_upload_page_is_never_limited(self):
        for _ in range(5):
            self.assertEqual(self.client.get(reverse('documents:bulk_upload')).status_code, 200)


@override_settings(ZIP_RATE_LIMIT=2, ZIP_RATE_LIMIT_WINDOW=600)
class ZipRateLimitTests(RateLimitTestCase):

    def test_the_download_past_the_limit_returns_to_the_repository_with_a_message(self):
        url = reverse('documents:download_area_zip') + '?area=all'
        self.client.get(url)
        self.client.get(url)
        r = self.client.get(url)
        self.assertRedirects(r, reverse('documents:repository'), fetch_redirect_response=False)
        texts = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any('Too many ZIP downloads' in t for t in texts), texts)


@override_settings(CHATBOT_RATE_LIMIT=2, CHATBOT_RATE_LIMIT_WINDOW=60)
class WindowTests(TestCase):
    """The window is fixed: steady use below the limit never adds up to a block."""

    def setUp(self):
        cache.clear()
        self.request = RequestFactory().post('/chatbot/api/')
        self.request.user = make_user('rl_window')

    def tearDown(self):
        cache.clear()

    def allowed_at(self, *times):
        results = []
        with mock.patch('qa_archiving_system.rate_limit.time') as clock:
            for t in times:
                clock.time.return_value = 1_000_000 + t
                results.append(rate_limit.allow(self.request, 'chatbot'))
        return results

    def test_steady_use_below_the_limit_is_never_refused(self):
        # One message every 40 seconds is 1.5 a minute, under 2 a minute.
        self.assertEqual(self.allowed_at(0, 40, 80, 120, 160, 200, 240), [True] * 7)

    def test_a_burst_is_refused_until_its_window_ends(self):
        self.assertEqual(self.allowed_at(0, 1, 2, 59, 60), [True, True, False, False, True])

    def test_the_limit_is_described_for_messages(self):
        self.assertEqual(rate_limit.describe_limit('chatbot'), '2 per minute')
        with self.settings(UPLOAD_RATE_LIMIT=15, UPLOAD_RATE_LIMIT_WINDOW=600):
            self.assertEqual(rate_limit.describe_limit('upload'), '15 per 10 minutes')

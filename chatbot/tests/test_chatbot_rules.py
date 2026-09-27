"""Tests for system-scoped chatbot responses."""
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from chatbot.chatbot_rules import get_chatbot_response
from chatbot.scope import is_off_topic, is_system_related, wants_document_context
from chatbot.system_status import get_system_stats, match_live_data_query
from documents.models import Document


class ChatbotScopeTests(TestCase):
    def test_system_related_upload_question(self):
        self.assertTrue(is_system_related('where do i upload documents'))

    def test_off_topic_weather(self):
        self.assertTrue(is_off_topic('what is the weather today'))

    def test_system_question_not_off_topic(self):
        self.assertFalse(is_off_topic('how do i upload a pdf to the repository'))

    def test_document_context_only_when_asked(self):
        self.assertTrue(wants_document_context('what does my uploaded policy document say'))
        self.assertFalse(wants_document_context('where is the dashboard'))


class ChatbotResponseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cb_user', 'cb@example.com', 'testpass123')
        self.factory = RequestFactory()
        self.request = self.factory.get('/chatbot/')
        self.request.user = self.user

    def test_off_topic_gets_refusal(self):
        r = get_chatbot_response('tell me a joke about cats', self.request)
        self.assertEqual(r['category'], 'out_of_scope')
        self.assertIn('QA Archiving System', r['answer'])

    def test_off_topic_hello_refused_quickly(self):
        r = get_chatbot_response('hello there', self.request)
        self.assertEqual(r['category'], 'out_of_scope')

    def test_off_topic_general_question(self):
        r = get_chatbot_response('who is the president of the united states', self.request)
        self.assertEqual(r['category'], 'out_of_scope')

    def test_navigation_upload(self):
        r = get_chatbot_response('where do I upload documents', self.request)
        self.assertIn('upload', r['answer'].lower())
        self.assertGreaterEqual(r['confidence'], 0.85)

    def test_broad_help_gives_step_by_step(self):
        r = get_chatbot_response('help me navigate', self.request)
        self.assertEqual(r['category'], 'system_overview')
        self.assertIn('step by step', r['answer'].lower())
        self.assertNotIn('127.0.0.1', r['answer'])
        self.assertNotIn('http://', r['answer'])

    def test_dashboard_system_knowledge(self):
        r = get_chatbot_response('what does the dashboard show', self.request)
        self.assertIn('dashboard', r['answer'].lower())

    def test_empty_message_prompts_system_scope(self):
        r = get_chatbot_response('   ', self.request)
        self.assertIn('QA Archiving System', r['answer'])


def _make_doc(title, **kwargs):
    defaults = dict(
        title=title,
        file=f'uploaded_documents/2024/01/{title}.pdf',
        file_type='pdf',
        year=2024,
        document_type='Policy',
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


class ChatbotLiveDataTests(TestCase):
    """The assistant should answer from real system data, scoped by permission."""

    def setUp(self):
        self.admin = User.objects.create_superuser('cb_admin', 'a@example.com', 'pass12345')
        self.plain = User.objects.create_user('cb_plain', 'p@example.com', 'pass12345')
        self.factory = RequestFactory()

    def _req(self, user):
        req = self.factory.get('/chatbot/')
        req.user = user
        return req

    def test_total_documents_answered_from_db(self):
        _make_doc('alpha', uploaded_by=self.admin)
        _make_doc('beta', uploaded_by=self.admin)
        r = get_chatbot_response('how many documents do I have', self._req(self.admin))
        self.assertEqual(r['category'], 'live_data')
        self.assertIn('2', r['answer'])

    def test_archived_documents_excluded_from_count(self):
        _make_doc('live-one', uploaded_by=self.admin)
        _make_doc('old-version', uploaded_by=self.admin, is_archived=True)
        stats = get_system_stats(self.admin)
        self.assertEqual(stats['total_documents'], 1)

    def test_duplicates_reported(self):
        _make_doc('dup', uploaded_by=self.admin, duplicate_status='possible')
        r = get_chatbot_response('how many duplicates are there', self._req(self.admin))
        self.assertEqual(r['category'], 'live_data')
        self.assertIn('1', r['answer'])

    def test_latest_documents_uses_live_data(self):
        _make_doc('newest-report', uploaded_by=self.admin)
        r = get_chatbot_response('show me the latest documents', self._req(self.admin))
        self.assertEqual(r['category'], 'live_data')
        self.assertIn('newest-report', r['answer'])

    def test_recent_uploads_not_confused_with_upload_howto(self):
        _make_doc('recent-doc', uploaded_by=self.admin)
        r = get_chatbot_response('what are the most recent uploads', self._req(self.admin))
        self.assertEqual(r['category'], 'live_data')

    def test_permissionless_user_gets_no_live_data(self):
        _make_doc('secret', uploaded_by=self.admin)
        # An inactive account loses repository access, so no live data is exposed.
        profile = getattr(self.plain, 'profile', None)
        if profile is not None:
            profile.status = 'inactive'
            profile.save()
        self.assertIsNone(match_live_data_query('how many documents are there', self._req(self.plain)))
        r = get_chatbot_response('how many documents are there', self._req(self.plain))
        self.assertNotEqual(r['category'], 'live_data')

    def test_offtopic_quantitative_not_hijacked(self):
        r = get_chatbot_response('how many countries are in the world', self._req(self.admin))
        self.assertNotEqual(r['category'], 'live_data')
        self.assertEqual(r['category'], 'out_of_scope')

    def test_admin_only_user_count(self):
        r = get_chatbot_response('how many users are there', self._req(self.admin))
        self.assertEqual(r['category'], 'live_data')
        self.assertIn('user', r['answer'].lower())


class ChatbotMemoryTests(TestCase):
    """Conversation turns are persisted in the session for follow-ups."""

    def setUp(self):
        self.admin = User.objects.create_superuser('cb_mem', 'm@example.com', 'pass12345')
        self.factory = RequestFactory()

    def _session_req(self):
        req = self.factory.get('/chatbot/')
        req.user = self.admin
        req.session = SessionStore()
        return req

    def test_turn_saved_to_session(self):
        req = self._session_req()
        get_chatbot_response('where do I upload documents', req)
        history = req.session.get('qa_chat_history')
        self.assertTrue(history)
        self.assertEqual(history[-1]['user'], 'where do I upload documents')

    def test_history_capped(self):
        req = self._session_req()
        for i in range(10):
            get_chatbot_response(f'where do I upload documents {i}', req)
        history = req.session.get('qa_chat_history')
        self.assertLessEqual(len(history), 6)

"""
Tests for which language model the chatbot falls back to.

The chatbot answers most questions from its own tiers and only consults a model
for what is left. These tests cover that last tier: that the default behaviour
is unchanged, that the hosted model is parsed correctly, and above all that no
failure of a hosted service can leave the chatbot with nothing to say.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from chatbot import chatbot_rules


def gemini_reply(text):
    """A minimal copy of the shape Google's generateContent returns."""
    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {'candidates': [{'content': {'parts': [{'text': text}]}}]}

    return Reply()


def failed_reply(status, body='{"error": {"message": "nope"}}'):
    class Reply:
        status_code = status
        text = body

        @staticmethod
        def json():
            return {}

    return Reply()


class ModelSelectionTests(SimpleTestCase):
    """_model_answer picks the configured provider and nothing else."""

    def setUp(self):
        patcher = patch.object(chatbot_rules, '_scoped_prompt', return_value='PROMPT')
        patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(CHATBOT_LLM_PROVIDER='none')
    def test_provider_none_asks_no_model(self):
        with patch.object(chatbot_rules, 'requests') as http:
            self.assertIsNone(chatbot_rules._model_answer('where do I upload?', None))
        http.post.assert_not_called()

    @override_settings(CHATBOT_LLM_PROVIDER='ollama')
    def test_default_provider_still_calls_ollama(self):
        with patch.object(chatbot_rules, '_ollama_answer',
                          return_value={'answer': 'local'}) as local:
            result = chatbot_rules._model_answer('where do I upload?', None)
        self.assertEqual(result['answer'], 'local')
        local.assert_called_once()

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='test-key')
    def test_gemini_answer_is_returned(self):
        with patch.object(chatbot_rules.requests, 'post',
                          return_value=gemini_reply('Upload from the sidebar.')) as post:
            result = chatbot_rules._model_answer('where do I upload?', None)
        self.assertEqual(result['answer'], 'Upload from the sidebar.')
        self.assertEqual(result['category'], 'ai_generated')
        # The key travels in a header, never in the query string, so it cannot
        # be captured by a proxy log or a browser history.
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'test-key')
        self.assertNotIn('test-key', post.call_args.args[0])


class GeminiFailureTests(SimpleTestCase):
    """Every way the hosted model can fail leaves the chatbot still answering."""

    def setUp(self):
        patcher = patch.object(chatbot_rules, '_scoped_prompt', return_value='PROMPT')
        patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='',
                       GEMINI_FALLBACK_TO_OLLAMA=False)
    def test_missing_key_is_not_an_exception(self):
        self.assertIsNone(chatbot_rules._gemini_answer('anything', None))

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='test-key',
                       GEMINI_FALLBACK_TO_OLLAMA=True)
    def test_quota_exhausted_falls_back_to_the_local_model(self):
        with patch.object(chatbot_rules.requests, 'post', return_value=failed_reply(429)):
            with patch.object(chatbot_rules, '_ollama_answer',
                              return_value={'answer': 'local'}) as local:
                result = chatbot_rules._model_answer('where do I upload?', None)
        self.assertEqual(result['answer'], 'local')
        local.assert_called_once()

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='test-key',
                       GEMINI_FALLBACK_TO_OLLAMA=False)
    def test_unknown_model_name_returns_none_rather_than_raising(self):
        with patch.object(chatbot_rules.requests, 'post', return_value=failed_reply(404)):
            self.assertIsNone(chatbot_rules._model_answer('where do I upload?', None))

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='test-key',
                       GEMINI_FALLBACK_TO_OLLAMA=False)
    def test_blocked_or_empty_reply_returns_none(self):
        class Empty:
            status_code = 200
            text = '{}'

            @staticmethod
            def json():
                return {'candidates': []}

        with patch.object(chatbot_rules.requests, 'post', return_value=Empty()):
            self.assertIsNone(chatbot_rules._gemini_answer('anything', None))


class SharedPromptTests(SimpleTestCase):
    """Both providers must be given the same system-only prompt."""

    @override_settings(CHATBOT_LLM_PROVIDER='gemini', GEMINI_API_KEY='test-key',
                       CHATBOT_OLLAMA_ENABLED=True)
    def test_both_providers_send_the_same_prompt(self):
        with patch.object(chatbot_rules, '_scoped_prompt', return_value='SCOPED') as prompt:
            with patch.object(chatbot_rules.requests, 'post',
                              return_value=gemini_reply('ok')) as post:
                chatbot_rules._gemini_answer('question', None)
                gemini_body = post.call_args.kwargs['json']

            with patch.object(chatbot_rules.requests, 'post',
                              return_value=gemini_reply('ok')) as post:
                post.return_value.json = staticmethod(lambda: {'response': 'ok'})
                chatbot_rules._ollama_answer('question', None)
                ollama_body = post.call_args.kwargs['json']

        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(gemini_body['contents'][0]['parts'][0]['text'], 'SCOPED')
        self.assertEqual(ollama_body['prompt'], 'SCOPED')

"""
Tests for the QA Archive Agent.

Three things are pinned here: that differently-worded questions reach the same
intent, that answers come from the records rather than from invention, and that
the agent stays inside the caller's permissions.
"""
from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from documents.models import Document

from chatbot import agent_nlu as nlu
from chatbot.agent import answer as agent_answer
from chatbot.models import Conversation


def _request(user):
    request = RequestFactory().post('/chatbot/api/')
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request.user = user
    return request


class IntentTests(TestCase):
    """Meaning, not keywords."""

    def test_four_phrasings_share_one_intent(self):
        phrasings = [
            'Find accreditation documents.',
            'Show me files related to accreditation.',
            'What accreditation records do we have?',
            'I need the documents for accreditation.',
        ]
        intents = {nlu.understand(p).intent for p in phrasings}
        self.assertEqual(intents, {nlu.FIND_DOCUMENTS})

    def test_missing_evidence_phrasings(self):
        for message in ('What documents are missing?',
                        "Which evidence haven't we uploaded?",
                        'What do we still need for PQA?'):
            self.assertEqual(nlu.understand(message).intent, nlu.MISSING_EVIDENCE,
                             msg=message)

    def test_summary_and_classification_are_distinguished(self):
        self.assertEqual(nlu.understand('Summarize this document.').intent, nlu.SUMMARIZE)
        self.assertEqual(nlu.understand('What is this file about?').intent, nlu.SUMMARIZE)
        self.assertEqual(
            nlu.understand('Why is this document classified under ISO Audit?').intent,
            nlu.EXPLAIN_CLASSIFICATION)

    def test_entities_are_extracted(self):
        u = nlu.understand('Find faculty evaluation records from 2025.')
        self.assertEqual(u.year, 2025)
        self.assertIn('faculty', u.topics)
        self.assertIn('evaluation', u.topics)

    def test_programme_recognised(self):
        self.assertEqual(nlu.understand('What do we still need for PQA?').program, 'PQA')

    def test_misspellings_are_repaired(self):
        u = nlu.understand('find acreditation documnets')
        self.assertEqual(u.intent, nlu.FIND_DOCUMENTS)
        self.assertIn('accreditation', [fixed for _, fixed in u.corrections])

    def test_follow_up_and_ordinal_are_recognised(self):
        follow_up = nlu.understand('Which ones are from 2025?')
        self.assertTrue(follow_up.refers_to_previous)
        self.assertEqual(follow_up.year, 2025)
        self.assertEqual(nlu.understand('Summarize the second one.').ordinal, 2)


class AgentAnswerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent_admin', 'a@e.com', 'testpass123')
        self.user.profile.role = 'admin'
        self.user.profile.save()
        self.request = _request(self.user)
        self.doc = Document.objects.create(
            title='Accreditation Self-Survey Report',
            file='uploaded_documents/2025/01/survey.pdf',
            file_type='pdf', year=2025, document_type='Report',
            qa_area='Area I',
            extracted_text=('The accreditation self-survey documents the programme. '
                            'It records the evidence gathered for each area and the '
                            'findings of the internal review committee. '
                            'Recommendations follow from those findings.'),
            tfidf_keywords=[['accreditation', 0.4], ['evidence', 0.3]],
        )

    def test_search_returns_cards_from_the_archive(self):
        result = agent_answer('Find accreditation documents.', self.request)
        self.assertIsNotNone(result)
        self.assertEqual(result['intent'], nlu.FIND_DOCUMENTS)
        titles = [c['title'] for c in result['cards']]
        self.assertIn(self.doc.title, titles)

    def test_response_keeps_the_existing_contract(self):
        result = agent_answer('Find accreditation documents.', self.request)
        for key in ('answer', 'category', 'cards', 'actions'):
            self.assertIn(key, result)

    def test_follow_up_narrows_the_previous_results(self):
        agent_answer('Find accreditation documents.', self.request)
        narrowed = agent_answer('Which ones are from 2025?', self.request)
        self.assertIsNotNone(narrowed)
        self.assertTrue(all(c['year'] == 2025 for c in narrowed['cards']))

    def test_ordinal_resolves_against_previous_results(self):
        agent_answer('Find accreditation documents.', self.request)
        summary = agent_answer('Summarize the first one.', self.request)
        self.assertEqual(summary['intent'], nlu.SUMMARIZE)
        self.assertTrue(summary['cards'])

    def test_summary_sentences_come_from_the_document(self):
        agent_answer('Find accreditation documents.', self.request)
        summary = agent_answer('Summarize the first one.', self.request)
        # every sentence in the summary must exist in the stored text
        body = summary['answer'].split('\n\n', 1)[-1].split('\n\nKey terms')[0]
        for sentence in [s.strip() for s in body.split('.') if len(s.strip()) > 20]:
            self.assertIn(sentence, self.doc.extracted_text)

    def test_classification_explained_from_stored_values(self):
        agent_answer('Find accreditation documents.', self.request)
        explained = agent_answer('Why is this document classified that way?', self.request)
        self.assertEqual(explained['intent'], nlu.EXPLAIN_CLASSIFICATION)
        self.assertIn('Report', explained['answer'])

    def test_no_results_is_stated_not_invented(self):
        result = agent_answer('Find laboratory documents from 1999.', self.request)
        self.assertIsNotNone(result)
        self.assertEqual(result['cards'], [])
        self.assertIn('No documents', result['answer'])

    def test_evaluation_is_searched_not_split_into_invented_kinds(self):
        """
        This asked the user to choose between Faculty, Curriculum and Student
        Evaluation. None of the three is a document type in this archive and no
        document title contains any of them, so every option led to an empty
        result. The question is now answered by searching, like any other.
        """
        result = agent_answer('Show me the evaluation documents.', self.request)
        self.assertIsNotNone(result)
        self.assertFalse(result.get('clarify'))
        self.assertNotIn('Faculty Evaluation', result['answer'])

    def test_off_topic_is_declined_so_the_rules_engine_answers(self):
        self.assertIsNone(agent_answer('tell me a joke about cats', self.request))
        self.assertIsNone(agent_answer('how many countries are in the world', self.request))

    def test_navigation_is_left_to_the_existing_engine(self):
        self.assertIsNone(agent_answer('where is upload', self.request))
        self.assertIsNone(agent_answer('what does the dashboard show', self.request))


class AgentScopeTests(TestCase):
    """Faculty must not reach documents outside their assigned areas."""

    def setUp(self):
        self.faculty = User.objects.create_user('agent_fac', 'f@e.com', 'testpass123')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()
        Document.objects.create(
            title='Area IX Laboratory Report',
            file='uploaded_documents/2025/01/lab.pdf',
            file_type='pdf', year=2025, document_type='Report', qa_area='Area IX',
        )

    def test_faculty_search_is_area_scoped(self):
        result = agent_answer('Find laboratory documents.', _request(self.faculty))
        if result is not None:
            for card in result['cards']:
                self.assertNotEqual(card['area'], 'Area IX')


class ConversationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent_conv', 'c@e.com', 'testpass123')
        self.user.profile.role = 'admin'
        self.user.profile.save()
        self.client.login(username='agent_conv', password='testpass123')

    def test_title_is_generated_from_the_first_question(self):
        self.assertEqual(
            Conversation.title_from('Find accreditation documents from 2025.'),
            'Accreditation Documents 2025')

    def test_thread_stores_both_turns_and_their_cards(self):
        response = self.client.post(
            '/chatbot/api/',
            data={'message': 'Find accreditation documents.', 'start_conversation': True},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        conversation = Conversation.objects.filter(user=self.user).first()
        self.assertIsNotNone(conversation)
        self.assertEqual(conversation.messages.count(), 2)

    def test_threads_are_private_to_their_owner(self):
        other = User.objects.create_user('agent_other', 'o@e.com', 'testpass123')
        other.profile.role = 'admin'
        other.profile.save()
        theirs = Conversation.objects.create(user=other, title='Theirs')
        self.assertEqual(self.client.get(f'/chatbot/conversations/{theirs.pk}/').status_code, 404)

    def test_rename_and_soft_delete(self):
        conversation = Conversation.objects.create(user=self.user, title='Before')
        self.client.post(f'/chatbot/conversations/{conversation.pk}/rename/',
                         data={'title': 'After'}, content_type='application/json')
        conversation.refresh_from_db()
        self.assertEqual(conversation.title, 'After')

        self.client.post(f'/chatbot/conversations/{conversation.pk}/delete/')
        conversation.refresh_from_db()
        self.assertTrue(conversation.is_deleted)
        listed = self.client.get('/chatbot/conversations/').json()['conversations']
        self.assertNotIn(conversation.pk, [c['id'] for c in listed])

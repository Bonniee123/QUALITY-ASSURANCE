"""
The assistant describes only what this system has.

Audited against the code, not against memory:

* `qa_structure` defines `AccreditationArea` and nothing else. `qa_mapping`
  defines `QAProgram` and nothing else. There is no Parameter, no Indicator and
  no Required Evidence model, table or page. The rules engine nevertheless
  defined all three, and explained "Parameter A" as a subdivision of an area,
  while the navigation answer a few files away said plainly that parameters,
  indicators and required-evidence lines are not tracked here. Two answers, one
  system, one of them true.

* `Document.evidence_status` exists as a column but appears only in the model,
  the admin and a migration -- no view and no template reads it. It is not a
  feature a user can see, so the assistant must not offer to work with it.

* The five row icons became one Actions menu, so "click the pencil icon",
  "click the eye icon" and "click the trash icon" named controls that are no
  longer on the row.

* "How do I map evidence?" was offered as a thing to try, by the same file whose
  answer says there is no evidence-mapping page.
"""
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from chatbot import chatbot_rules
from chatbot.system_navigation import navigation_topics


class InventedStructureTests(SimpleTestCase):

    def test_the_qa_hierarchy_is_only_what_the_models_hold(self):
        from qa_mapping import models as mapping_models
        from qa_structure import models as structure_models
        from django.db.models import Model

        def model_names(module):
            return {n for n, o in vars(module).items()
                    if isinstance(o, type) and issubclass(o, Model) and o.__module__ == module.__name__}

        self.assertEqual(model_names(structure_models), {'AccreditationArea'})
        self.assertEqual(model_names(mapping_models), {'QAProgram'})

    def test_the_assistant_no_longer_defines_them(self):
        for question in ('what is a parameter', 'what is an indicator',
                         'what is required evidence', 'what is parameter a'):
            answer = chatbot_rules.match_accreditation_faq(question, None)
            self.assertIsNone(answer, question)

    def test_it_still_defines_what_does_exist(self):
        for question in ('what is an area', 'what is a qa program', 'how do i upload a document'):
            self.assertIsNotNone(chatbot_rules.match_accreditation_faq(question, None), question)

    def test_the_navigation_answer_says_they_are_not_tracked(self):
        topic = next(t for t in navigation_topics(None) if t['id'] == 'qa_structure')
        self.assertIn('not tracked in this system', topic['answer'])


class StaleControlTests(SimpleTestCase):

    def rules_text(self):
        return ' '.join(str(v) for v in chatbot_rules.SYSTEM_KNOWLEDGE.values())

    def test_no_answer_names_a_row_icon_that_is_gone(self):
        text = self.rules_text()
        for gone in ('pencil icon', 'eye icon', 'trash icon'):
            self.assertNotIn(gone, text)
        self.assertIn('Actions menu', text)

    def test_nothing_offers_evidence_mapping(self):
        source = (settings.BASE_DIR / 'chatbot' / 'chatbot_rules.py').read_text(encoding='utf-8')
        self.assertNotIn('How do I map evidence?', source)


class AssistantCopyTests(SimpleTestCase):

    def page(self, name):
        return (settings.BASE_DIR / 'templates' / 'chatbot' / name).read_text(encoding='utf-8')

    def test_the_page_does_not_promise_evidence_features(self):
        body = self.page('chatbot.html')
        # Header copy and the composer placeholder only -- the script below
        # them carries a comment naming what was removed and why.
        visible = body[body.index('<p>Ask about'):body.index('{% endblock %}')]
        self.assertNotIn('evidence', visible)

    def test_the_floating_dock_lists_real_pages(self):
        """
        The floating widget is now the Messages dock, and the assistant is the
        first conversation in it. Its greeting is the one the old widget used,
        so the same scope claim is asserted where it now lives.
        """
        dock = (settings.BASE_DIR / 'templates' / 'messaging'
                / 'floating_messages.html').read_text(encoding='utf-8')
        self.assertNotIn('search, evidence, and reports', dock)
        self.assertIn('document groups', dock)


class OutstandingEvidenceTests(TestCase):

    def test_the_answer_says_why_it_cannot_be_given(self):
        """
        "I couldn't determine what evidence is outstanding" reads like a lookup
        that failed. Nothing in the archive records what ought to exist, so the
        answer now says that, and points at the two pages that do help.
        """
        from django.contrib.auth.models import User
        from django.test import RequestFactory
        from chatbot.agent import answer as agent_answer

        user = User.objects.create_user('ev_head', 'e@example.com', 'Str0ng-Passw0rd!')
        user.profile.role = 'qa_staff'
        user.profile.save()
        request = RequestFactory().get('/')
        request.user = user

        result = agent_answer('What documents are missing for PQA?', request)
        self.assertIsNotNone(result)
        self.assertIn('does not record what evidence is required', result['answer'])
        self.assertIn('Area Submissions', result['answer'])


class SidebarCoverageTests(SimpleTestCase):
    """
    Every page in the sidebar has a topic.

    Document Groups and Messages are in the sidebar for every role and had no
    topic at all, so "what is Document Groups" and "how do I message the QA
    Head" fell through to the generic overview.
    """

    def topic_ids(self):
        return {t['id'] for t in navigation_topics(None)}

    def test_document_groups_and_messages_are_covered(self):
        self.assertIn('document_groups', self.topic_ids())
        self.assertIn('messages', self.topic_ids())

    def test_both_are_offered_to_every_role(self):
        from chatbot.system_navigation import _STAFF_ONLY_TOPICS
        self.assertNotIn('document_groups', _STAFF_ONLY_TOPICS)
        self.assertNotIn('messages', _STAFF_ONLY_TOPICS)

    def test_the_answers_name_only_real_parts_of_those_pages(self):
        topics = {t['id']: t['answer'] for t in navigation_topics(None)}
        groups = topics['document_groups']
        self.assertIn('No category', groups)
        self.assertIn('Search within this group', groups)
        messages = topics['messages']
        self.assertIn('attach a document', messages)
        self.assertNotIn('evidence', messages.lower())


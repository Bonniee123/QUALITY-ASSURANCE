"""
Questions the QA Assistant answered wrongly or not at all.

Each case was asked of the assistant with sample data loaded and answered badly:
"summarize the fire safety certificate" summarised whatever the previous answer
was about; "how many documents are in Area II?" gave the archive-wide total;
"what are the accreditation areas?" described QA programmes; "which documents
were uploaded this week?" and "who can see my uploads?" got the upload steps;
"hi", "thanks", "how do I change my password?" and "what does Needs review
mean?" were refused as off-topic.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

from chatbot.agent import _extractive_summary
from chatbot.chatbot_rules import get_chatbot_response
from documents.models import Document
from qa_structure.models import AccreditationArea


def _request(user):
    request = RequestFactory().post('/chatbot/api/')
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request.user = user
    return request


def _user(username, role, areas=()):
    user = User.objects.create_user(username, f'{username}@e.com', 'pw-12345-x',
                                    first_name=username.title())
    user.profile.role = role
    user.profile.save()
    if areas:
        user.profile.assigned_areas.set(AccreditationArea.objects.filter(area_code__in=areas))
    return user


class AnswerQualityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        for code, name in (('Area II', 'Faculty'), ('Area VIII', 'Physical Plant and Facilities'),
                           ('Area IX', 'Laboratories')):
            AccreditationArea.objects.update_or_create(area_code=code, defaults={'area_name': name})
        area = {a.area_code: a for a in AccreditationArea.objects.all()}

        def doc(title, code, text, days_ago=0, **extra):
            d = Document.objects.create(
                title=title, file=f'uploaded_documents/{title[:10]}.pdf', file_type='pdf', year=2025,
                document_type=extra.pop('document_type', 'Report'), acc_area=area[code], qa_area=code,
                extracted_text=text, **extra)
            Document.objects.filter(pk=d.pk).update(uploaded_at=timezone.now() - timedelta(days=days_ago))
            return d

        cls.plan = doc('Faculty Development Plan', 'Area II',
                       'Faculty development plan. Targets for graduate study and research output for faculty.')
        cls.report = doc('Faculty Qualifications Report', 'Area II',
                         'Faculty qualifications. Most faculty hold graduate degrees in their field.', days_ago=20)
        cls.cert = doc('CERTIFICATE OF COMPLIANCE', 'Area VIII', '', document_type='Certificate',
                       ocr_text='Certificate of compliance. Fire safety inspection of the main building passed.')
        cls.admin = _user('quality_admin', 'admin')
        cls.faculty = _user('quality_fac', 'faculty', areas=['Area II'])

    def ask(self, user, *messages):
        request = _request(user)
        for message in messages:
            result = get_chatbot_response(message, request)
        return result

    # ------------------------------------------------------------ documents

    def test_a_named_document_is_summarised_not_the_previous_answer(self):
        r = self.ask(self.admin, 'Show me documents about faculty', 'Summarize the fire safety certificate')
        self.assertEqual([c['id'] for c in r['cards']], [self.cert.pk])
        self.assertIn('Fire safety inspection', r['answer'])

    def test_the_first_one_still_refers_to_the_previous_answer(self):
        first = self.ask(self.admin, 'Show me documents about faculty')['cards'][0]['id']
        request = _request(self.admin)
        get_chatbot_response('Show me documents about faculty', request)
        r = get_chatbot_response('summarize the first one', request)
        self.assertEqual(r['cards'][0]['id'], first)

    def test_a_name_that_matches_nothing_is_said_so(self):
        r = self.ask(self.admin, 'Show me documents about faculty', 'Summarize the zebra crossing memo')
        self.assertEqual(r['cards'], [])
        self.assertIn("couldn't find a document", r['answer'])

    def test_faculty_cannot_summarise_a_document_outside_their_area_by_name(self):
        r = self.ask(self.faculty, 'Summarize the fire safety certificate')
        self.assertEqual(r['cards'], [])
        self.assertNotIn('Fire safety', r['answer'])

    def test_why_was_it_put_in_an_area(self):
        r = self.ask(self.admin, 'Why was the certificate put in Area VIII?')
        self.assertEqual(r['intent'], 'explain_classification')
        self.assertEqual(r['cards'][0]['id'], self.cert.pk)
        self.assertIn('Area VIII', r['answer'])

    def test_a_summary_says_a_repeated_sentence_once(self):
        text = ('The faculty development fund supports graduate study for full-time faculty members. ' * 3
                + 'Research output targets are reviewed by the dean every semester without exception.')
        summary = _extractive_summary(text, self.plan)
        self.assertEqual(summary.count('The faculty development fund'), 1)

    # --------------------------------------------------------- counts, areas

    def test_a_count_narrowed_to_an_area(self):
        r = self.ask(self.admin, 'How many documents are in Area II?')
        self.assertIn('**2**', r['answer'])
        self.assertIn('Area II', r['answer'])

    def test_a_plain_count_stays_with_the_live_totals(self):
        self.assertEqual(self.ask(self.admin, 'how many documents do we have')['category'], 'live_data')

    def test_the_accreditation_areas_are_listed(self):
        r = self.ask(self.admin, 'What are the accreditation areas?')
        self.assertEqual(r['intent'], 'area_info')
        for line in ('**Area II** — Faculty (2 documents)', '**Area IX** — Laboratories (0 documents)'):
            self.assertIn(line, r['answer'])

    def test_one_area_is_described_with_what_it_holds(self):
        r = self.ask(self.admin, 'What is Area II about?')
        self.assertIn('Area II — Faculty', r['answer'])
        self.assertEqual({c['id'] for c in r['cards']}, {self.plan.pk, self.report.pk})

    def test_what_to_upload_is_answered_honestly(self):
        r = self.ask(self.admin, 'What should I upload for Area IX?')
        self.assertIn('does not keep a list of the evidence', r['answer'])
        self.assertIn('Nothing is archived in it yet', r['answer'])

    def test_faculty_see_no_counts_for_areas_not_assigned_to_them(self):
        r = self.ask(self.faculty, 'What is Area VIII about?')
        self.assertIn('not assigned to you', r['answer'])
        self.assertEqual(r['cards'], [])

    def test_uploads_in_a_period(self):
        r = self.ask(self.admin, 'Which documents were uploaded this week?')
        self.assertEqual(r['intent'], 'uploaded_in_period')
        self.assertEqual({c['id'] for c in r['cards']}, {self.plan.pk, self.cert.pk})
        self.assertIn('last 7 days', r['answer'])

    def test_uploads_in_a_period_are_scoped_for_faculty(self):
        r = self.ask(self.faculty, 'What was uploaded this week?')
        self.assertEqual([c['id'] for c in r['cards']], [self.plan.pk])

    # ------------------------------------------------------ help and manners

    def test_greetings_and_thanks_are_answered(self):
        self.assertIn('Hello, Quality_Admin!', self.ask(self.admin, 'hi')['answer'])
        self.assertEqual(self.ask(self.admin, 'salamat po')['category'], 'small_talk')
        self.assertIn("You're welcome", self.ask(self.admin, 'Thank you!')['answer'])

    def test_a_greeting_with_a_question_is_answered_as_the_question(self):
        self.assertNotEqual(self.ask(self.admin, 'hi, how do I upload a document?')['category'], 'small_talk')

    def test_how_to_questions_that_had_no_answer(self):
        cases = {
            'How do I change my password?': 'Passwords are managed by an Administrator',
            'Who can see my uploads?': 'Who can see a document depends on its accreditation area',
            'What does Needs review mean?': 'marked Needs review',
            'How do I mark a duplicate as clear?': 'Mark as clear',
            'How do I download all documents of Area II?': 'Download area as ZIP',
        }
        for question, expected in cases.items():
            self.assertIn(expected, self.ask(self.admin, question)['answer'], msg=question)

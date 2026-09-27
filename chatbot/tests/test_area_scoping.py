"""
The QA Assistant only talks about documents the asker may open.

Its live numbers ("how many documents", "how many duplicates", "recent uploads")
and the document text it passes to the local LLM were read from the whole
archive, so a Faculty member assigned to Area III was told the archive-wide
totals and the titles of the latest uploads in every other area. Everything now
goes through the Repository's own area scope.
"""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from chatbot.chatbot_rules import _fetch_document_context
from chatbot.system_status import get_system_stats, live_context_text
from documents.models import Document
from qa_structure.models import AccreditationArea


class _Archive(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area2, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.area3, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        cls.staff = User.objects.create_user('scope_qa', password='pass12345')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()
        cls.fac3 = User.objects.create_user('scope_fac3', password='pass12345')
        cls.fac3.profile.role = 'faculty'
        cls.fac3.profile.save()
        cls.fac3.profile.assigned_areas.add(cls.area3)
        cls.nobody = User.objects.create_user('scope_none', password='pass12345')
        cls.nobody.profile.role = 'faculty'
        cls.nobody.profile.save()

        def doc(title, area, status='none', text=''):
            return Document.objects.create(
                title=title, file=f'uploaded_documents/2026/09/{title}.pdf', file_type='pdf', year=2026,
                document_type='Report', qa_area=area.area_code, acc_area=area, uploaded_by=cls.staff,
                duplicate_status=status, extracted_text=text or f'{title} body text')

        cls.mine = doc('Curriculum map for nursing', cls.area3, text='curriculum map nursing outcomes')
        cls.other = doc('Zebra crossing guide', cls.area2, status='possible',
                        text='zebra crossing guide for the east gate pedestrian lanes')
        cls.other2 = doc('Faculty ranking results', cls.area2, status='possible', text='faculty ranking results')


class LiveNumbersTests(_Archive):

    def test_faculty_numbers_count_only_their_areas(self):
        stats = get_system_stats(self.fac3)
        self.assertEqual(stats['total_documents'], 1)
        self.assertEqual([r['title'] for r in stats['recent']], ['Curriculum map for nursing'])
        # Duplicate review is QA work, so the count is not scoped down for a
        # Faculty member -- it is not given to them at all, which is how the
        # Repository, the group pages and the Dashboard already treat it.
        self.assertNotIn('duplicates', stats)
        self.assertNotIn('clusters', stats)

    def test_staff_still_see_the_whole_archive(self):
        stats = get_system_stats(self.staff)
        self.assertEqual(stats['total_documents'], 3)
        self.assertEqual(stats['duplicates'], 2)

    def test_faculty_without_an_area_see_nothing(self):
        stats = get_system_stats(self.nobody)
        self.assertEqual(stats['total_documents'], 0)
        self.assertEqual(stats['recent'], [])

    def test_the_answer_says_whose_numbers_these_are(self):
        text = live_context_text(self.fac3)
        self.assertIn('in your area(s) Area III: 1', text)
        self.assertNotIn('Zebra crossing guide', text)

    def test_through_the_chat_api(self):
        client = Client()
        client.force_login(self.fac3)
        for question in ('How many documents are there?', 'What are the recent uploads?', 'How many duplicates?'):
            answer = client.post('/chatbot/api/', json.dumps({'message': question}),
                                 content_type='application/json').json()['answer']
            with self.subTest(question):
                self.assertNotIn('Zebra crossing guide', answer)
                self.assertNotIn('Faculty ranking results', answer)
                self.assertNotRegex(answer, r'\b3\b', 'the archive-wide total must not appear')


class LlmContextTests(_Archive):

    def test_document_snippets_for_the_llm_stay_in_scope(self):
        request = type('R', (), {'user': self.fac3})()
        context = _fetch_document_context('which document: zebra crossing', request)
        self.assertNotIn('pedestrian lanes', context)
        staff_request = type('R', (), {'user': self.staff})()
        self.assertIn('pedestrian lanes', _fetch_document_context('which document: zebra crossing',
                                                                  staff_request))

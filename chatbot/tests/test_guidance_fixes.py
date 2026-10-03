"""
The assistant answers what was asked, and its guidance matches the real UI.

Measured before the change (C2b, C3, S-DR-07):

* "show me documents about zebra crossing", "which documents mention rainwater
  harvesting" and two similar questions were all answered with the upload
  steps: any message containing "document" matched the upload topic.
* "How do I delete a document?" got the upload steps; "Where is the QA
  Checklist?" got the Repository steps ("list" matched inside "checklist").
* The upload steps described a single-file form, although the sidebar opens the
  multi-file page; only Admins were said to delete (QA Heads can too); the
  Elbow method was said to choose the cluster count; Settings was said to be
  editable; version history was said to be in the document details.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from chatbot.system_navigation import match_navigation_topic
from documents.models import Document
from qa_structure.models import AccreditationArea


class _Asker(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area2, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.area3, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        cls.staff = User.objects.create_user('guide_qa', password='pass12345')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()
        cls.fac3 = User.objects.create_user('guide_fac3', password='pass12345')
        cls.fac3.profile.role = 'faculty'
        cls.fac3.profile.save()
        cls.fac3.profile.assigned_areas.add(cls.area3)
        for title, area, text in (
                ('Zebra crossing guide', cls.area2, 'zebra crossing guide for the east gate pedestrian lanes'),
                ('Rainwater harvesting plan', cls.area3, 'the campus plan for rainwater harvesting tanks')):
            Document.objects.create(title=title, file=f'uploaded_documents/{title}.pdf', file_type='pdf',
                                    year=2026, document_type='Plan', qa_area=area.area_code, acc_area=area,
                                    extracted_text=text)

    def ask(self, user, question):
        self.client.force_login(user)
        return self.client.post('/chatbot/api/', json.dumps({'message': question}),
                                content_type='application/json').json()['answer']


class DocumentQuestionTests(_Asker):

    def test_a_subject_outside_the_known_topics_is_searched(self):
        answer = self.ask(self.staff, 'show me documents about zebra crossing')
        self.assertNotIn('Open Upload Document', answer)
        self.assertIn('I found 1 document', answer)

    def test_mention_questions_are_searched(self):
        answer = self.ask(self.fac3, 'which documents mention rainwater harvesting')
        self.assertIn('I found 1 document', answer)

    def test_faculty_are_told_when_nothing_matches_in_their_areas(self):
        answer = self.ask(self.fac3, 'documents about pedestrian lanes at the east gate')
        self.assertNotIn('Open Upload Document', answer)
        self.assertIn('No documents in your area(s)', answer)
        self.assertNotIn('Zebra crossing guide', answer, 'the Area II document stays out of reach')


class NavigationAnswerTests(TestCase):

    def nav(self, question):
        found = match_navigation_topic(question.lower(), None)
        return found[0] if found else ''

    def test_delete_gets_delete_steps_for_every_role(self):
        answer = self.nav('How do I delete a document?')
        # The five row icons became one kebab menu, so "trash icon" named a
        # control that is no longer on the row.
        self.assertIn('Actions menu', answer)
        self.assertNotIn('trash icon', answer)
        self.assertIn('Administrators and QA Heads can delete any document', answer)

    def test_the_checklist_question_is_not_the_repository(self):
        self.assertIn('There is no QA Checklist page', self.nav('Where is the QA Checklist?'))

    def test_upload_describes_the_page_the_sidebar_opens(self):
        answer = self.nav('Where do I upload?')
        self.assertIn('single file or many at once', answer)
        self.assertNotIn('Fill title, year', answer)

    def test_clusters_say_what_chooses_k(self):
        self.assertIn('chosen by the silhouette score', self.nav('How are clusters chosen?'))

    def test_settings_are_read_only(self):
        self.assertIn('read-only', self.nav('Where are the settings?'))

    def test_a_word_inside_another_word_does_not_match(self):
        # "ai" inside "email", "list" inside "checklist".
        self.assertNotIn('Document Analysis', self.nav('where do I change my email address'))

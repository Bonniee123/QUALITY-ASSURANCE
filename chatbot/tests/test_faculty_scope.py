"""
What the QA Assistant tells a Faculty member.

Two problems. The assistant read out figures that Faculty are not shown
anywhere else -- the duplicate count and the cluster count -- and pointed them
at "the Dashboard duplicates KPI or the Repository duplicates filter", both of
which were removed for their role. And `navigation_topics` returned every
topic to everyone, so Faculty were walked through Reports, Document Analysis, User
Management, Settings, Area Submissions and Clusters: six pages that are not in
their sidebar and that the server refuses.

It also advertised work the system does not do. The starter suggestion "What
documents are missing for PQA?" reaches `_handle_missing`, which answers "I
couldn't determine what evidence is outstanding" every time, because both
sources that once backed it were removed as out of scope. "Show me faculty
evaluation records" reached a menu offering Faculty, Curriculum and Student
Evaluation -- none of which is a document type here, and none of which appears
in any document title.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from chatbot.system_navigation import _STAFF_ONLY_TOPICS, navigation_topics
from chatbot.system_status import get_system_stats
from documents.models import Document
from qa_structure.models import AccreditationArea


class _Req:
    def __init__(self, user):
        self.user = user


def make_user(username, role, areas=()):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    for area in areas:
        user.profile.assigned_areas.add(area)
    return user


class AssistantScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.faculty = make_user('bot_fac', 'faculty', [cls.area])
        cls.head = make_user('bot_head', 'qa_staff')
        Document.objects.create(
            title='Filed evidence', file='uploaded_documents/b.pdf', file_type='pdf',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            uploaded_by=cls.faculty, cluster_label=4, duplicate_status='possible')

    def test_faculty_are_not_given_duplicate_or_cluster_counts(self):
        stats = get_system_stats(self.faculty)
        self.assertNotIn('duplicates', stats)
        self.assertNotIn('clusters', stats)
        self.assertIn('total_documents', stats)
        self.assertIn('scope_areas', stats)

    def test_staff_still_get_them(self):
        stats = get_system_stats(self.head)
        self.assertIn('duplicates', stats)
        self.assertIn('clusters', stats)

    def test_faculty_are_not_walked_through_pages_they_cannot_open(self):
        ids = {t['id'] for t in navigation_topics(_Req(self.faculty))}
        self.assertFalse(ids & _STAFF_ONLY_TOPICS, 'no staff-only topic survives')
        for kept in ('upload', 'repository', 'search', 'delete', 'notifications'):
            self.assertIn(kept, ids)

    def test_staff_keep_every_topic(self):
        ids = {t['id'] for t in navigation_topics(_Req(self.head))}
        self.assertTrue(_STAFF_ONLY_TOPICS <= ids)

    def test_the_off_topic_scorer_still_sees_everything(self):
        """It decides whether a message is about this system, not what to answer."""
        self.assertTrue(_STAFF_ONLY_TOPICS <= {t['id'] for t in navigation_topics(None)})

    def test_the_delete_steps_name_the_control_that_exists(self):
        """The five row icons became one Actions menu; the steps said "trash icon"."""
        delete = next(t for t in navigation_topics(None) if t['id'] == 'delete')
        self.assertIn('Actions menu', delete['answer'])
        self.assertNotIn('trash icon', delete['answer'])


class InventedCategoryTests(TestCase):

    def test_the_evaluation_options_are_gone(self):
        """
        Faculty, Curriculum and Student Evaluation are not document types in
        this archive, and no document title contains any of them, so every
        option led to an empty result.
        """
        from chatbot.agent import _AMBIGUOUS_TOPICS
        self.assertEqual(_AMBIGUOUS_TOPICS, {})

    def test_the_starter_suggestions_all_reach_a_working_handler(self):
        from django.conf import settings
        page = (settings.BASE_DIR / 'templates' / 'chatbot' / 'chatbot.html').read_text(encoding='utf-8')
        self.assertNotIn("'What documents are missing for PQA?'", page)
        self.assertNotIn("'Show me faculty evaluation records'", page)
        for kept in ("'Find accreditation documents'",
                     "'How many documents have I uploaded?'",
                     "'Show me the most recent uploads'",
                     "'Where do I upload documents?'"):
            self.assertIn(kept, page)

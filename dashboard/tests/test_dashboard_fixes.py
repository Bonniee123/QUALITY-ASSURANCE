"""
Dashboard fixes from the full system check.

* S-DR-01: "Next" from December went to December of the following year.
* S-DR-02: "today" was the UTC date while uploads are bucketed by local date.
* S-DR-03: a Faculty member's "Duplicates to Review" and "Uploaded This Week"
  cards opened the unfiltered Repository.
* S-DR-06: program counts included archived versions; the KPIs do not.
* S-SEC-02: exported program names starting with "=" were live formulas.
"""
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard.views import _calendar_nav_query, _parse_calendar_month
from documents.models import Document
from qa_mapping.models import QAProgram
from qa_structure.models import AccreditationArea


class CalendarTests(TestCase):

    def test_next_from_december_is_january(self):
        nav = _calendar_nav_query(RequestFactory().get('/'), 2026, 12, 'monthly', None)
        self.assertIn('cal=2027-01', nav['next_url'])
        self.assertEqual(nav['next_label'], 'Jan 2027')
        self.assertIn('cal=2026-11', nav['prev_url'])

    def test_today_is_the_local_date(self):
        # 23:30 UTC on 31 Dec is already 1 January in Manila.
        now = datetime(2026, 12, 31, 23, 30, tzinfo=ZoneInfo('UTC'))
        with timezone.override('Asia/Manila'):
            self.assertEqual(_parse_calendar_month(RequestFactory().get('/'), now), (2027, 1))


def make_user(username, role, areas=()):
    user = User.objects.create_user(username, password='pass12345')
    user.profile.role = role
    user.profile.save()
    for area in areas:
        user.profile.assigned_areas.add(area)
    return user


class KpiLinkTests(TestCase):

    def setUp(self):
        self.area, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        self.faculty = make_user('kpi_fac', 'faculty', [self.area])

        def doc(title, **extra):
            return Document.objects.create(title=title, file=f'uploaded_documents/{title}.pdf', file_type='pdf',
                                           year=2026, document_type='Report', acc_area=self.area,
                                           qa_area='Area III', **extra)

        self.flagged = doc('Flagged copy', duplicate_status='possible')
        self.clear = doc('Clear report')
        self.old = doc('Old upload')
        Document.objects.filter(pk=self.old.pk).update(uploaded_at=timezone.now() - timedelta(days=30))
        self.client.force_login(self.faculty)

    def titles(self, url):
        html = self.client.get(url).content.decode()
        return {t for t in ('Flagged copy', 'Clear report', 'Old upload') if t in html}

    def test_uploaded_this_week_opens_the_weeks_uploads(self):
        page = self.client.get(reverse('dashboard:home'))
        self.assertEqual(page.context['docs_last7'], 2)
        self.assertEqual(self.titles(page.context['week_repo_url']), {'Flagged copy', 'Clear report'})

    def test_faculty_do_not_get_the_staff_only_cards(self):
        # Making the duplicates card a dead card was not enough: an amber
        # "Action needed" still asked a Faculty member for something the server
        # refuses, and a cluster count led to a page they cannot open. Both are
        # gone for them; what they can act on stays.
        html = self.client.get(reverse('dashboard:home')).content.decode()
        self.assertNotIn('Duplicates to Review', html)
        self.assertNotIn('Document Clusters', html)
        self.assertNotIn('?duplicate=review', html)
        self.assertIn('Total Documents', html)
        self.assertIn('Uploaded This Week', html)
        self.assertIn('AI-Processed', html)

    def test_staff_duplicates_card_opens_the_flagged_list(self):
        head = make_user('kpi_head', 'qa_staff')
        self.client.force_login(head)
        page = self.client.get(reverse('dashboard:home'))
        body = page.content.decode()
        self.assertIn(f'href="{page.context["duplicate_repo_url"]}"', body)
        self.assertIn('Document Clusters', body)
        self.assertEqual(self.titles(page.context['duplicate_repo_url']), {'Flagged copy'})

    def test_faculty_still_cannot_use_the_duplicate_filters(self):
        self.assertEqual(self.titles(reverse('documents:repository') + '?duplicate=review'),
                         {'Flagged copy', 'Clear report', 'Old upload'})


class ProgramCountTests(TestCase):

    def test_program_counts_leave_out_archived_versions(self):
        admin = make_user('prog_admin', 'admin')
        program = QAProgram.objects.create(name='QATEST Program', code='QTP', is_active=True)
        for archived in (False, False, True):
            Document.objects.create(title='d', file='uploaded_documents/d.pdf', file_type='pdf', year=2026,
                                    document_type='Report', program=program, is_archived=archived)
        self.client.force_login(admin)
        csv_text = self.client.get(reverse('dashboard:home') + '?export=csv').content.decode()
        self.assertIn('QA Programs,QTP,QATEST Program,2,,', csv_text)
        self.assertIn('Key Metrics,Total documents,2,', csv_text)


class ExportEscapingTests(TestCase):

    def test_a_formula_like_program_name_is_exported_as_text(self):
        admin = make_user('exp_admin', 'admin')
        QAProgram.objects.create(name='=HYPERLINK("http://evil.example","Click")', code='@SUM(A1)', is_active=True)
        self.client.force_login(admin)
        csv_text = self.client.get(reverse('dashboard:home') + '?export=csv').content.decode()
        self.assertIn("'@SUM(A1)", csv_text)
        self.assertIn("'=HYPERLINK", csv_text)

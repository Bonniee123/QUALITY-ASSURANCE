"""Lightweight HTTP and search smoke tests."""
import json
from unittest.mock import patch

from django.test import TestCase, Client
from django.test import override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.models import Document
from documents.views import _is_exact_duplicate_upload, _is_near_duplicate_upload
from search.search_service import search_documents, compute_facet_counts
from search.views import SEARCH_PAGE_SIZE
from notifications.models import Notification
from notifications.services import notify, notify_qa_staff
from documents.text_extraction import extract_text


class SmokeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('smoke_admin', 'a@example.com', 'testpass123')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        self.qa_head = User.objects.create_user('smoke_head', 'h@example.com', 'testpass123')
        self.qa_head.profile.role = 'qa_staff'
        self.qa_head.profile.save()

    def test_login_page_renders(self):
        r = self.client.get('/accounts/login/')
        self.assertEqual(r.status_code, 200)

    def test_dashboard_requires_login(self):
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r.url)

    def test_dashboard_admin_ok(self):
        self.client.login(username='smoke_admin', password='testpass123')
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 200)

    def test_dashboard_qa_head_ok(self):
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get('/dashboard/', follow=False)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Upload Activity')
        self.assertContains(r, 'File Formats')
        self.assertNotContains(r, 'Evidence Ready')

    def test_dashboard_duplicate_kpi_uses_duplicate_status(self):
        Document.objects.create(
            title='Dup doc',
            file='uploaded_documents/2026/05/dup.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            duplicate_status='possible',
        )
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Duplicates to Review')
        self.assertContains(r, '>1<', html=False)

    def test_dashboard_calendar_shows_upload_day(self):
        from django.utils import timezone
        doc = Document.objects.create(
            title='Cal doc',
            file='uploaded_documents/2026/05/cal.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
        )
        today = timezone.localdate()
        cal_param = today.strftime('%Y-%m')
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get(f'/dashboard/?cal={cal_param}&day={today.isoformat()}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Upload Activity')
        self.assertContains(r, doc.title[:20])

    def test_repository_duplicate_review_filter(self):
        Document.objects.create(
            title='Unique doc',
            file='uploaded_documents/2026/05/u.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            duplicate_status='none',
        )
        Document.objects.create(
            title='Dup filter doc',
            file='uploaded_documents/2026/05/d.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            duplicate_status='possible',
        )
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get('/documents/repository/?duplicate=review')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Dup filter doc')
        self.assertNotContains(r, 'Unique doc')

    def test_repository_qa_head_ok(self):
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get('/documents/repository/')
        self.assertEqual(r.status_code, 200)

    def test_repository_xhr_returns_pagination_json(self):
        self.client.login(username='smoke_head', password='testpass123')
        r = self.client.get(
            '/documents/repository/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content.decode())
        self.assertIn('html', data)
        self.assertIn('count_html', data)
        self.assertIn('has_more', data)
        self.assertIn('next_page', data)
        self.assertIn('total', data)


class SearchTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            title='Annual Report',
            file='uploaded_documents/2026/05/dummy.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            extracted_text='nothing relevant here',
            tfidf_keywords=[['accreditation', 0.9], ['compliance', 0.7]],
        )

    def test_search_filters_by_file_type(self):
        docx = Document.objects.create(
            title='Word Doc',
            file='uploaded_documents/2026/05/dummy.docx',
            file_type='docx',
            year=2026,
            document_type='Report',
        )
        pdf_results = list(search_documents('', filters={'file_type': 'pdf'}))
        self.assertIn(self.doc, pdf_results)
        self.assertNotIn(docx, pdf_results)
        docx_results = list(search_documents('', filters={'file_type': 'docx'}))
        self.assertIn(docx, docx_results)
        self.assertNotIn(self.doc, docx_results)

    def test_search_matches_tfidf_keyword(self):
        results = list(search_documents('accreditation'))
        self.assertIn(self.doc, results)

    def test_search_matches_extracted_text(self):
        results = list(search_documents('relevant'))
        self.assertIn(self.doc, results)

    def test_search_invalid_year_filter_is_ignored(self):
        results = list(search_documents('', filters={'year': 'not-a-year'}))
        self.assertIn(self.doc, results)

    def test_smart_search_xhr_returns_json(self):
        head = User.objects.create_user('search_xhr', 'sx@example.com', 'testpass123')
        head.profile.role = 'qa_staff'
        head.profile.save()
        self.client.login(username='search_xhr', password='testpass123')
        r = self.client.get(
            '/documents/repository/',
            {'q': 'Annual'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content.decode())
        self.assertIn('html', data)
        self.assertIn('count_html', data)
        self.assertIn('total', data)
        self.assertIn('has_more', data)
        self.assertIn('next_page', data)
        self.assertIn('page', data)

    def test_smart_search_xhr_pagination_has_more(self):
        token = 'ZZPagTokenZZ'
        Document.objects.bulk_create(
            [
                Document(
                    title=f'{token} bulk {i}',
                    file=f'uploaded_documents/2026/05/zpag_{i}.pdf',
                    file_type='pdf',
                    year=2026,
                    document_type='Memo',
                )
                for i in range(SEARCH_PAGE_SIZE + 1)
            ]
        )
        head = User.objects.create_user('search_pag', 'sp@example.com', 'testpass123')
        head.profile.role = 'qa_staff'
        head.profile.save()
        self.client.login(username='search_pag', password='testpass123')

        r1 = self.client.get(
            '/documents/repository/',
            {'q': token},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r1.status_code, 200)
        d1 = json.loads(r1.content.decode())
        self.assertEqual(d1['total'], SEARCH_PAGE_SIZE + 1)
        self.assertTrue(d1['has_more'])
        self.assertEqual(d1['next_page'], 2)
        self.assertEqual(d1['page'], 1)
        # The repository's rows carry attributes (class, data-doc-id), so count the
        # row class rather than a bare '<tr>'.
        self.assertEqual(d1['html'].count('class="doc-row'), SEARCH_PAGE_SIZE)

        r2 = self.client.get(
            '/documents/repository/',
            {'q': token, 'page': '2'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r2.status_code, 200)
        d2 = json.loads(r2.content.decode())
        self.assertEqual(d2['total'], SEARCH_PAGE_SIZE + 1)
        self.assertFalse(d2['has_more'])
        self.assertIsNone(d2['next_page'])
        self.assertEqual(d2['page'], 2)
        self.assertEqual(d2['html'].count('class="doc-row'), 1)

    @override_settings(ENABLE_HYBRID_SMART_SEARCH=True, HYBRID_SEARCH_CANDIDATE_POOL=50, HYBRID_SEARCH_MAX_RANKED=20)
    def test_hybrid_search_reranks_by_relevance(self):
        strong = Document.objects.create(
            title='Accreditation Policy Compliance Manual',
            file='uploaded_documents/2026/05/strong.pdf',
            file_type='pdf',
            year=2026,
            document_type='Manual',
        )
        weak = Document.objects.create(
            title='Random Memo',
            file='uploaded_documents/2026/05/weak.pdf',
            file_type='pdf',
            year=2026,
            document_type='Memorandum',
            extracted_text='mentions accreditation once',
        )
        results = list(search_documents('accreditation policy compliance')[:2])
        self.assertEqual(results[0].pk, strong.pk)
        self.assertGreaterEqual(len(results), 1)


class ExtractionAndDuplicateTests(TestCase):
    @override_settings(ENABLE_PDF_OCR_FALLBACK=True, PDF_OCR_MIN_TEXT_CHARS=5)
    @patch('documents.text_extraction.extract_text_from_scanned_pdf', return_value='ocr from scanned pdf')
    @patch('documents.text_extraction.extract_text_from_pdf', return_value='')
    def test_pdf_ocr_fallback_method_used(self, _pdf, _ocr):
        text, method = extract_text('fake_scanned.pdf')
        self.assertEqual(method, 'pdf_ocr_fallback')
        self.assertIn('ocr from scanned pdf', text)

    @override_settings(ENABLE_PDF_OCR_FALLBACK=False)
    @patch('documents.text_extraction.extract_text_from_pdf', return_value='')
    def test_pdf_ocr_fallback_disabled(self, _pdf):
        text, method = extract_text('fake_scanned.pdf')
        self.assertEqual(method, 'pdf_extraction')
        self.assertEqual(text, '')

    def test_exact_duplicate_helper_detects_same_file(self):
        content = b'%PDF-1.4\nsame-content\n%%EOF\n'
        existing_file = SimpleUploadedFile('existing.pdf', content, content_type='application/pdf')
        Document.objects.create(
            title='Existing',
            file=existing_file,
            file_type='pdf',
            year=2026,
            document_type='Report',
        )
        incoming = SimpleUploadedFile('incoming.pdf', content, content_type='application/pdf')
        self.assertTrue(_is_exact_duplicate_upload(incoming, '.pdf'))

    @override_settings(DUPLICATE_PREUPLOAD_MIN_TEXT_CHARS=20, DUPLICATE_PREUPLOAD_TEXT_THRESHOLD=0.85)
    @patch('documents.views.extract_text')
    def test_near_duplicate_helper_detects_similar_text(self, mock_extract):
        Document.objects.create(
            title='Existing Similar',
            file='uploaded_documents/2026/05/existing_sim.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
            extracted_text='This is a quality assurance policy document for accreditation and compliance.',
        )
        mock_extract.return_value = (
            'This is a quality assurance policy document for accreditation and compliance with updates.',
            'pdf_extraction',
        )
        incoming = SimpleUploadedFile(
            'incoming_sim.pdf',
            b'%PDF-1.4\nnear duplicate test\n%%EOF\n',
            content_type='application/pdf',
        )
        self.assertTrue(_is_near_duplicate_upload(incoming, '.pdf'))


class VersioningTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('ver_staff', 'v@example.com', 'testpass123')
        self.staff.profile.role = 'qa_staff'
        self.staff.profile.save()
        self.older = Document.objects.create(
            title='Policy v1', file='uploaded_documents/2025/01/p1.pdf', file_type='pdf',
            year=2025, document_type='Policy',
        )
        self.newer = Document.objects.create(
            title='Policy v2', file='uploaded_documents/2026/01/p2.pdf', file_type='pdf',
            year=2026, document_type='Policy',
        )

    def test_archived_hidden_by_default(self):
        self.older.is_archived = True
        self.older.save()
        results = list(search_documents(''))
        self.assertNotIn(self.older, results)
        self.assertIn(self.newer, results)

    def test_archived_visible_when_requested(self):
        self.older.is_archived = True
        self.older.save()
        results = list(search_documents('', include_archived=True))
        self.assertIn(self.older, results)

    def test_mark_as_version_archives_older(self):
        self.client.login(username='ver_staff', password='testpass123')
        r = self.client.post(
            f'/documents/{self.newer.pk}/mark-as-version/',
            {'previous_id': self.older.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.older.refresh_from_db()
        self.newer.refresh_from_db()
        self.assertTrue(self.older.is_archived)
        self.assertEqual(self.newer.previous_version_id, self.older.pk)

    def test_version_chain_links_old_to_new(self):
        self.newer.previous_version = self.older
        self.newer.save()
        chain = self.newer.version_chain()
        self.assertEqual(chain[0], self.older)
        self.assertEqual(chain[-1], self.newer)


class NotificationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('notif_user', 'n@example.com', 'testpass123')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()

    def test_notify_creates_record(self):
        n = notify(self.user, 'hello world', category='system', link='/dashboard/')
        self.assertIsNotNone(n)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        self.assertFalse(n.is_read)

    def test_notify_qa_staff_targets_admin_and_qa_head(self):
        admin = User.objects.create_user('notif_admin', 'a@example.com', 'testpass123')
        admin.profile.role = 'admin'
        admin.profile.save()
        sent = notify_qa_staff('staff-only message', category='system')
        self.assertGreaterEqual(sent, 2)
        self.assertEqual(Notification.objects.filter(user=admin).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_mark_read_endpoint(self):
        n = notify(self.user, 'unread item')
        self.client.login(username='notif_user', password='testpass123')
        r = self.client.post(f'/notifications/{n.pk}/read/')
        self.assertIn(r.status_code, (200, 302))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_all_read_ajax(self):
        notify(self.user, 'unread one')
        notify(self.user, 'unread two')
        self.client.login(username='notif_user', password='testpass123')
        r = self.client.post(
            '/notifications/mark-all-read/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(),
            0,
        )

    def test_notification_list_removed(self):
        self.client.login(username='notif_user', password='testpass123')
        r = self.client.get('/notifications/')
        self.assertEqual(r.status_code, 404)


class FacetCountsTests(TestCase):
    def setUp(self):
        Document.objects.create(
            title='A', file='uploaded_documents/2026/01/a.pdf', file_type='pdf',
            year=2026, document_type='Report',
            extracted_text='alpha',
        )
        Document.objects.create(
            title='B', file='uploaded_documents/2026/01/b.pdf', file_type='pdf',
            year=2025, document_type='Report',
            extracted_text='beta',
        )
        Document.objects.create(
            title='C', file='uploaded_documents/2026/01/c.pdf', file_type='pdf',
            year=2025, document_type='Policy',
            extracted_text='gamma',
        )

    def test_facet_counts_basic(self):
        counts = compute_facet_counts('', filters={})
        self.assertEqual(counts['year'].get(2026), 1)
        self.assertEqual(counts['year'].get(2025), 2)
        self.assertEqual(counts['document_type'].get('Report'), 2)
        self.assertEqual(counts['document_type'].get('Policy'), 1)

    def test_facet_counts_respect_other_filters(self):
        counts = compute_facet_counts('', filters={'document_type': 'Policy'})
        self.assertEqual(counts['year'].get(2025), 1)
        self.assertNotIn(2026, counts['year'])
        self.assertEqual(counts['document_type'].get('Report'), 2)
        self.assertEqual(counts['document_type'].get('Policy'), 1)

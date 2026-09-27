"""
What happens to a file whose text cannot be read, and what the uploader is told.

Measured before the change (J1, O3, O7, O8, O10, O11):

* A damaged Word file was stored as processed, with no error and no text, and
  the batch notification counted it among "10 documents uploaded successfully
  and ready in the Repository" -- while clustering was still running.
* With Tesseract missing, an image said only "OCR/extraction produced no text."
* A phone photo stored sideways (EXIF orientation) OCR'd as gibberish, and image
  OCR ignored OCR_LANGUAGE.
* A scanned PDF past the page limit, or over the size limit, lost its later
  pages / all its text from search with nothing said on the document.
* Retry OCR on a Word file marked it "OCR failed", and new OCR text did not
  refresh keywords, clusters or duplicates.
"""
import io
import os
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from documents import jobs
from documents.models import BackgroundJob, Document
from documents.text_extraction import (
    _upright, explain_extraction, extract_text_from_image, is_damaged_file_problem, ocr_unavailable_reason,
)
from notifications.user_messages import bulk_upload_notification_message


def docx_bytes(text):
    from docx import Document as WordDocument
    buf = io.BytesIO()
    word = WordDocument()
    word.add_paragraph(text)
    word.save(buf)
    return buf.getvalue()


class TempFileMixin:

    def temp_file(self, suffix, payload):
        handle, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(handle, 'wb') as fh:
            fh.write(payload)
        self.addCleanup(os.remove, path)
        return path

    def blank_pdf(self, pages=1):
        import fitz
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page()
        data = doc.tobytes()
        doc.close()
        return self.temp_file('.pdf', data)


class ExplanationTests(TempFileMixin, SimpleTestCase):

    def test_a_damaged_word_file_is_a_failure_not_an_empty_document(self):
        path = self.temp_file('.docx', b'PK\x03\x04' + b'\x00garbage' * 20)
        problem, notice = explain_extraction(path, '', 'docx_extraction')
        self.assertIn('Could not read this Word document', problem)
        self.assertTrue(is_damaged_file_problem(problem))

    def test_a_valid_but_empty_word_file_is_fine(self):
        path = self.temp_file('.docx', docx_bytes(''))
        self.assertEqual(explain_extraction(path, '', 'docx_extraction'), ('', ''))

    def test_missing_tesseract_is_named(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(buf, 'PNG')
        path = self.temp_file('.png', buf.getvalue())
        with mock.patch('pytesseract.get_tesseract_version', side_effect=OSError('not found')):
            problem, _notice = explain_extraction(path, '', 'ocr_failed')
            self.assertIn('Tesseract program was not found', problem)
            self.assertEqual(problem, ocr_unavailable_reason())
        self.assertFalse(is_damaged_file_problem(problem), 'the file itself is fine')

    def test_an_oversized_image_gets_a_clear_message(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), 'white').save(buf, 'PNG')
        path = self.temp_file('.png', buf.getvalue())
        with mock.patch.object(Image, 'MAX_IMAGE_PIXELS', 100):
            problem, _notice = explain_extraction(path, '', 'ocr_failed')
        self.assertIn('too large to read', problem)

    @override_settings(PDF_OCR_MAX_PAGES=6)
    def test_a_scanned_pdf_past_the_page_limit_says_so(self):
        path = self.blank_pdf(pages=10)
        _problem, notice = explain_extraction(path, 'text from the first pages', 'pdf_ocr_fallback')
        self.assertIn('only the first 6 of its 10 pages were read by OCR', notice)

    @override_settings(PDF_OCR_MAX_FILE_MB=0)
    def test_a_scanned_pdf_over_the_size_limit_says_so(self):
        path = self.blank_pdf()
        problem, notice = explain_extraction(path, '', 'pdf_extraction')
        self.assertIn('OCR was skipped', notice)
        self.assertEqual(problem, '', 'a large scan is not a damaged file')

    def test_a_damaged_pdf(self):
        path = self.temp_file('.pdf', b'%PDF-1.4 not really a pdf')
        problem, _notice = explain_extraction(path, '', 'pdf_extraction')
        self.assertTrue(is_damaged_file_problem(problem))


class ImageOcrTests(TempFileMixin, SimpleTestCase):

    def test_the_image_is_turned_upright_and_read_in_the_configured_language(self):
        from PIL import Image
        img = Image.new('RGB', (40, 20), 'white')
        exif = img.getexif()
        exif[0x0112] = 6  # stored sideways: rotate 90 degrees to view
        buf = io.BytesIO()
        img.save(buf, 'JPEG', exif=exif.tobytes())
        path = self.temp_file('.jpg', buf.getvalue())
        seen = {}

        def fake_ocr(image, lang=None):
            seen['size'], seen['lang'] = image.size, lang
            return 'upright text'

        with override_settings(OCR_LANGUAGE='eng+fil'), \
                mock.patch('pytesseract.image_to_string', side_effect=fake_ocr):
            self.assertEqual(extract_text_from_image(path), 'upright text')
        self.assertEqual(seen, {'size': (20, 40), 'lang': 'eng+fil'})

    def test_an_image_without_orientation_is_unchanged(self):
        from PIL import Image
        img = Image.new('RGB', (40, 20))
        self.assertEqual(_upright(img).size, (40, 20))


def make_user(username='qa_head', role='qa_staff'):
    user = User.objects.create_user(username, f'{username}@example.com', 'pass12345')
    user.profile.role = role
    user.profile.save()
    return user


class BatchOutcomeTests(TestCase):

    def test_a_damaged_file_is_reported_as_failed_and_not_counted_as_uploaded(self):
        user = make_user()
        good = Document.objects.create(title='good', file=SimpleUploadedFile('good.docx', docx_bytes('Minutes ' * 30)),
                                       file_type='docx', year=2026, document_type='Minutes', uploaded_by=user)
        bad = Document.objects.create(title='bad', file=SimpleUploadedFile('bad.docx', b'PK\x03\x04' + b'\x00' * 64),
                                      file_type='docx', year=2026, document_type='Minutes', uploaded_by=user)
        job = BackgroundJob.objects.create(job_type='bulk_upload_process', created_by=user,
                                           payload={'document_ids': [good.pk, bad.pk], 'total_count': 2})
        with mock.patch('documents.jobs.request_full_pipeline'):
            jobs._run_bulk_upload_process(job)
        job.refresh_from_db()
        bad.refresh_from_db()
        good.refresh_from_db()
        self.assertIn('Could not read this Word document', bad.processing_error)
        self.assertEqual(good.processing_error, '')
        self.assertEqual(job.payload['succeeded_count'], 1)
        message = bulk_upload_notification_message(job, success=True)
        self.assertIn('1 document uploaded successfully', message)
        self.assertIn('1 file could not be processed', message)

    def test_the_message_does_not_say_ready_while_analysis_runs(self):
        user = make_user()
        job = BackgroundJob.objects.create(job_type='bulk_upload_process', created_by=user, payload={
            'total_count': 3, 'processed_count': 3, 'succeeded_count': 3, 'errors': [],
            'analysis_requested_at': '2026-09-14T10:00:00+00:00'})
        message = bulk_upload_notification_message(job, success=True)
        self.assertNotIn('ready', message)
        self.assertIn('Duplicate checks and clustering will finish shortly', message)

    def test_the_detail_panel_shows_the_failure(self):
        user = make_user()
        self.client.force_login(user)
        doc = Document.objects.create(title='bad', file='uploaded_documents/bad.docx', file_type='docx', year=2026,
                                      document_type='Minutes', processing_error='Could not read this Word document.')
        html = self.client.get(reverse('documents:detail', args=[doc.pk]) + '?panel=1').content.decode()
        self.assertIn('Processing Error', html)
        self.assertIn('Could not read this Word document.', html)


class DeletedUploaderTests(TestCase):
    """Found during this check: a document whose uploader was deleted could not be opened (500)."""

    def test_the_document_still_opens(self):
        head = make_user('head_viewer')
        gone = make_user('leaver', role='faculty')
        doc = Document.objects.create(title='Left behind', file='uploaded_documents/l.pdf', file_type='pdf',
                                      year=2026, document_type='Report', uploaded_by=gone)
        gone.delete()  # uploaded_by is SET_NULL
        self.client.force_login(head)
        for url in (reverse('documents:detail', args=[doc.pk]), reverse('documents:detail', args=[doc.pk]) + '?panel=1'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'Left behind')


class RetryOcrTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_retry_on_a_word_file_is_explained_not_failed(self):
        doc = Document.objects.create(title='w', file='uploaded_documents/w.docx', file_type='docx', year=2026,
                                      document_type='Minutes')
        with mock.patch('documents.views.enqueue_job') as enqueue:
            response = self.client.post(reverse('documents:retry_ocr', args=[doc.pk]), follow=True)
        enqueue.assert_not_called()
        doc.refresh_from_db()
        self.assertEqual(doc.ocr_status, 'not_run')
        self.assertContains(response, 'OCR does not apply to Word or Excel files')

    def test_a_text_pdf_is_not_marked_ocr_failed_and_new_text_refreshes_the_analysis(self):
        doc = Document.objects.create(title='p', file=SimpleUploadedFile('p.pdf', b'%PDF-1.4 x'), file_type='pdf',
                                      year=2026, document_type='Report', ocr_status='failed')
        with mock.patch('documents.jobs.extract_text', return_value=('text layer words ' * 20, 'pdf_extraction')), \
                mock.patch('documents.jobs.request_full_pipeline') as refresh:
            jobs._reprocess_ocr({'only_empty': False, 'pdf_only': False, 'document_ids': [doc.pk]},
                                created_by=self.user, refresh_after=True)
        doc.refresh_from_db()
        self.assertEqual(doc.ocr_status, 'not_run')
        self.assertIn('text layer words', doc.extracted_text)
        refresh.assert_called_once_with(self.user)

    def test_new_ocr_text_is_stored(self):
        doc = Document.objects.create(title='s', file=SimpleUploadedFile('s.pdf', b'%PDF-1.4 x'), file_type='pdf',
                                      year=2026, document_type='Report', ocr_status='failed')
        with mock.patch('documents.jobs.extract_text', return_value=('scanned words', 'pdf_ocr_fallback')), \
                mock.patch('documents.jobs.explain_extraction', return_value=('', '')), \
                mock.patch('documents.jobs.request_full_pipeline') as refresh:
            jobs._reprocess_ocr({'only_empty': False, 'pdf_only': False, 'document_ids': [doc.pk]},
                                refresh_after=True)
        doc.refresh_from_db()
        self.assertEqual((doc.ocr_status, doc.ocr_text), ('success', 'scanned words'))
        refresh.assert_called_once()

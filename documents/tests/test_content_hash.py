"""Tests for Document.content_sha256 and the exact-duplicate upload check."""
import hashlib
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from documents.models import Document
from documents.views import _is_exact_duplicate_upload, _is_near_duplicate_upload


PDF_BYTES = b'%PDF-1.4 quality assurance manual body text'
OTHER_BYTES = b'%PDF-1.4 a completely different document entirely'


def _make_doc(title, payload, file_type='pdf', **extra):
    return Document.objects.create(
        title=title,
        file=SimpleUploadedFile(f'{title}.{file_type}', payload),
        file_type=file_type,
        year=2026,
        document_type='Report',
        **extra,
    )


class ContentHashTests(TestCase):
    def test_hash_is_computed_on_save(self):
        doc = _make_doc('hashed', PDF_BYTES)
        self.assertEqual(doc.content_sha256, hashlib.sha256(PDF_BYTES).hexdigest())

    def test_hash_is_persisted_not_just_in_memory(self):
        doc = _make_doc('persisted', PDF_BYTES)
        doc.refresh_from_db()
        self.assertEqual(doc.content_sha256, hashlib.sha256(PDF_BYTES).hexdigest())

    def test_different_content_gets_different_hash(self):
        a = _make_doc('doc-a', PDF_BYTES)
        b = _make_doc('doc-b', OTHER_BYTES)
        self.assertNotEqual(a.content_sha256, b.content_sha256)

    def test_ensure_content_hash_is_idempotent(self):
        doc = _make_doc('idempotent', PDF_BYTES)
        first = doc.content_sha256
        self.assertEqual(doc.ensure_content_hash(), first)

    def test_ensure_content_hash_returns_empty_when_file_missing(self):
        doc = Document.objects.create(
            title='no file on disk',
            file='uploaded_documents/2026/05/does-not-exist.pdf',
            file_type='pdf',
            year=2026,
            document_type='Report',
        )
        self.assertEqual(doc.content_sha256, '')
        self.assertEqual(doc.ensure_content_hash(), '')


class ExactDuplicateUploadTests(TestCase):
    def test_identical_bytes_are_rejected(self):
        _make_doc('original', PDF_BYTES)
        upload = SimpleUploadedFile('copy.pdf', PDF_BYTES)
        self.assertTrue(_is_exact_duplicate_upload(upload, '.pdf'))

    def test_different_bytes_are_allowed(self):
        _make_doc('original', PDF_BYTES)
        upload = SimpleUploadedFile('other.pdf', OTHER_BYTES)
        self.assertFalse(_is_exact_duplicate_upload(upload, '.pdf'))

    def test_archived_documents_do_not_block_reupload(self):
        _make_doc('superseded', PDF_BYTES, is_archived=True)
        upload = SimpleUploadedFile('again.pdf', PDF_BYTES)
        self.assertFalse(_is_exact_duplicate_upload(upload, '.pdf'))

    def test_matches_legacy_row_with_no_stored_hash_and_backfills_it(self):
        """Rows predating the column must still be caught, and get hashed on the way."""
        doc = _make_doc('legacy', PDF_BYTES)
        Document.objects.filter(pk=doc.pk).update(content_sha256='')

        upload = SimpleUploadedFile('copy.pdf', PDF_BYTES)
        self.assertTrue(_is_exact_duplicate_upload(upload, '.pdf'))

        doc.refresh_from_db()
        self.assertEqual(doc.content_sha256, hashlib.sha256(PDF_BYTES).hexdigest())

    def test_jpg_and_jpeg_are_one_format(self):
        """The same picture saved as .jpg and as .jpeg is an exact copy, not just 'visually similar'."""
        _make_doc('photo', PDF_BYTES, file_type='jpg')
        self.assertTrue(_is_exact_duplicate_upload(SimpleUploadedFile('photo.jpeg', PDF_BYTES), '.jpeg'))
        self.assertTrue(_is_exact_duplicate_upload(SimpleUploadedFile('photo.JPG', PDF_BYTES), '.JPG'))

    def test_other_formats_stay_separate(self):
        _make_doc('photo', PDF_BYTES, file_type='png')
        self.assertFalse(_is_exact_duplicate_upload(SimpleUploadedFile('photo.jpg', PDF_BYTES), '.jpg'))

    def test_upload_stream_is_rewound_for_the_caller(self):
        """The check consumes the upload to hash it; the view still has to save it."""
        _make_doc('original', PDF_BYTES)
        upload = SimpleUploadedFile('copy.pdf', PDF_BYTES)
        _is_exact_duplicate_upload(upload, '.pdf')
        self.assertEqual(upload.read(), PDF_BYTES)


class NearDuplicatePrefilterTests(TestCase):
    """
    The length/quick_ratio prefilters are exact upper bounds on SequenceMatcher.ratio(),
    so they must never change the answer — only how fast it is reached.
    """

    def setUp(self):
        self.body = ('quality assurance evidence for area one ' * 12).strip()

    def test_wildly_different_lengths_are_not_duplicates(self):
        _make_doc('long', self.body.encode())
        Document.objects.filter(title='long').update(extracted_text=self.body)

        upload = SimpleUploadedFile('short.pdf', b'%PDF-1.4 tiny')
        self.assertFalse(_is_near_duplicate_upload(upload, '.pdf'))

    def test_below_min_chars_is_skipped(self):
        upload = SimpleUploadedFile('tiny.pdf', b'%PDF-1.4 hi')
        self.assertFalse(_is_near_duplicate_upload(upload, '.pdf'))



class NearDuplicateUnextractedCandidateTests(TestCase):
    """
    A candidate whose text has not been extracted yet must still be compared.

    Text extraction runs in a background job, so for a short window after an
    upload the stored document has an empty ``extracted_text``. The check used to
    skip those candidates, which meant a duplicate uploaded during that window
    was invisible to it. Two revisions of the same 90,000-character thesis
    chapter -- byte-different, so the hash check passed them, but textually
    identical -- were archived 17 seconds apart exactly this way.

    ``extract_text`` is patched rather than fed a real document: these assert the
    control flow around extraction, not the extractor itself, and a fake PDF
    payload yields no text on any real parser.
    """

    def setUp(self):
        self.body = ('quality assurance evidence for area one ' * 20).strip()
        self.payload = f'%PDF-1.4 {self.body}'.encode()

    def _stored_doc_awaiting_extraction(self):
        doc = _make_doc('awaiting extraction', self.payload)
        Document.objects.filter(pk=doc.pk).update(extracted_text='')
        return doc

    def test_candidate_with_no_stored_text_is_still_compared(self):
        self._stored_doc_awaiting_extraction()
        upload = SimpleUploadedFile('same-content.pdf', self.payload)
        with mock.patch('documents.views.extract_text', return_value=(self.body, 'test')):
            self.assertTrue(
                _is_near_duplicate_upload(upload, '.pdf'),
                'a duplicate uploaded before extraction finished was let through',
            )

    def test_the_text_is_backfilled_so_the_work_happens_once(self):
        doc = self._stored_doc_awaiting_extraction()
        upload = SimpleUploadedFile('same-content.pdf', self.payload)
        with mock.patch('documents.views.extract_text', return_value=(self.body, 'test')):
            _is_near_duplicate_upload(upload, '.pdf')
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text, self.body)

    def test_a_different_document_is_still_allowed(self):
        self._stored_doc_awaiting_extraction()
        other = 'an entirely unrelated laboratory safety report ' * 20
        upload = SimpleUploadedFile('other.pdf', f'%PDF-1.4 {other}'.encode())
        # The stored candidate extracts to `self.body`; the upload reads as `other`.
        with mock.patch('documents.views.extract_text',
                        side_effect=lambda path: ((other, 'test') if 'tmp' in str(path).lower()
                                                  else (self.body, 'test'))):
            self.assertFalse(_is_near_duplicate_upload(upload, '.pdf'))

    def test_extraction_failure_leaves_the_candidate_skipped(self):
        self._stored_doc_awaiting_extraction()
        upload = SimpleUploadedFile('same-content.pdf', self.payload)
        with mock.patch('documents.views.extract_text', side_effect=OSError('unreadable')):
            self.assertFalse(_is_near_duplicate_upload(upload, '.pdf'))

    def test_missing_file_on_disk_does_not_raise(self):
        doc = self._stored_doc_awaiting_extraction()
        doc.file.storage.delete(doc.file.name)
        upload = SimpleUploadedFile('same-content.pdf', self.payload)
        with mock.patch('documents.views.extract_text', return_value=(self.body, 'test')):
            self.assertFalse(_is_near_duplicate_upload(upload, '.pdf'))

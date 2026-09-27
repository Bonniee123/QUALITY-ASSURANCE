"""
Uploads are checked to be what their extension says (S-UP-13), years are limited
on the server (S-UP-12), files past the batch cap are reported (S-UP-11), and a
very long file name no longer makes a title too long for MySQL (S-UP-14).

Measured before the change: a Windows program and an HTML page renamed to
".pdf" and an empty ".pdf" were all accepted by the bulk upload; a Faculty
upload with year 99999 was stored; a batch posted past the cap saved the first
files and said nothing about the rest.
"""
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from documents.models import Document
from documents.upload_validation import upload_content_problem


def png_bytes(size=(8, 8)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, (10, 20, 30)).save(buf, 'PNG')
    return buf.getvalue()


def jpeg_bytes(size=(8, 8)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 40, 40)).save(buf, 'JPEG')
    return buf.getvalue()


def office_bytes_with(kind, extra):
    """A real Office package with extra members added (name -> bytes)."""
    import zipfile
    original = zipfile.ZipFile(io.BytesIO(office_bytes(kind)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as out:
        for item in original.infolist():
            out.writestr(item.filename, original.read(item.filename))
        for name, payload in extra.items():
            out.writestr(name, payload)
    return buf.getvalue()


def office_bytes(kind):
    buf = io.BytesIO()
    if kind == 'docx':
        from docx import Document as WordDocument
        WordDocument().save(buf)
    else:
        from openpyxl import Workbook
        Workbook().save(buf)
    return buf.getvalue()


class ContentCheckTests(SimpleTestCase):

    def problem(self, name, payload, content_type=None):
        upload = SimpleUploadedFile(name, payload, content_type=content_type) if content_type \
            else SimpleUploadedFile(name, payload)
        return upload_content_problem(upload, '.' + name.rsplit('.', 1)[1])

    def test_real_files_pass(self):
        self.assertEqual(self.problem('a.pdf', b'%PDF-1.7\n...'), '')
        self.assertEqual(self.problem('a.png', png_bytes()), '')
        self.assertEqual(self.problem('a.jpg', jpeg_bytes()), '')
        self.assertEqual(self.problem('a.docx', office_bytes('docx')), '')
        self.assertEqual(self.problem('a.xlsx', office_bytes('xlsx')), '')

    def test_real_files_pass_with_the_browsers_own_content_type(self):
        self.assertEqual(self.problem('a.pdf', b'%PDF-1.7\n...', 'application/pdf'), '')
        self.assertEqual(self.problem('a.png', png_bytes(), 'image/png'), '')
        self.assertEqual(self.problem('a.jpg', jpeg_bytes(), 'application/octet-stream'), '')
        self.assertEqual(self.problem(
            'a.docx', office_bytes('docx'),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'), '')

    def test_renamed_programs_and_pages_are_refused(self):
        self.assertIn('not a real PDF', self.problem('setup.pdf', b'MZ\x90\x00\x03 windows program'))
        self.assertIn('not a real PDF', self.problem('page.pdf', b'<html><script>alert(1)</script></html>'))
        self.assertIn('not a real PNG', self.problem('photo.png', b'%PDF-1.4 a pdf'))

    def test_an_empty_file_is_refused(self):
        self.assertEqual(self.problem('blank.pdf', b''), 'the file is empty')

    def test_a_zip_is_not_a_word_document(self):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('notes.txt', 'hello')
        self.assertIn('not a real Word document', self.problem('notes.docx', buf.getvalue()))
        self.assertIn('not a real Excel workbook', self.problem('book.xlsx', office_bytes('docx')))

    def test_the_file_is_left_at_its_start(self):
        upload = SimpleUploadedFile('a.pdf', b'%PDF-1.4 body')
        upload_content_problem(upload, '.pdf')
        self.assertEqual(upload.read(), b'%PDF-1.4 body')


class DisguisedFileTests(SimpleTestCase):
    """
    A right-looking header is not proof.

    The signature check alone accepted anything that *started* like a picture or
    an Office package: the bytes after it were never looked at, a macro project
    inside a .docx was invisible, and a browser could offer a page as a PDF.
    """

    def problem(self, name, payload, content_type=None):
        upload = SimpleUploadedFile(name, payload, content_type=content_type) if content_type \
            else SimpleUploadedFile(name, payload)
        return upload_content_problem(upload, '.' + name.rsplit('.', 1)[1])

    def test_a_picture_that_is_only_a_header_is_refused(self):
        # Correct magic bytes, nothing behind them that decodes.
        self.assertIn('could not be opened', self.problem('fake.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 400))
        self.assertIn('could not be opened', self.problem('fake.jpg', b'\xff\xd8\xff\xe0 jfif'))

    def test_a_truncated_picture_is_refused(self):
        self.assertIn('could not be opened', self.problem('cut.png', png_bytes()[:60]))

    def test_a_picture_saved_under_the_wrong_extension_is_refused(self):
        # A real JPEG named .png: the header check alone would pass it as "not PNG",
        # but a real GIF renamed .png would previously reach storage.
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (8, 8)).save(buf, 'GIF')
        gif = buf.getvalue()
        self.assertIn('not a real PNG image', self.problem('sneaky.png', gif))

    def test_an_image_bigger_than_the_budget_is_refused(self):
        with mock.patch('documents.upload_validation._MAX_IMAGE_PIXELS', 16):
            self.assertIn('too large to open safely', self.problem('huge.png', png_bytes((8, 8))))

    def test_a_macro_project_inside_a_word_file_is_refused(self):
        payload = office_bytes_with('docx', {'word/vbaProject.bin': b'\x00macro'})
        self.assertIn('macro-enabled', self.problem('macro.docx', payload))

    def test_a_package_entry_escaping_the_folder_is_refused(self):
        payload = office_bytes_with('docx', {'../../evil.xml': b'<x/>'})
        self.assertIn('unsafe entry', self.problem('slip.docx', payload))

    def test_a_package_that_expands_absurdly_is_refused(self):
        payload = office_bytes_with('docx', {'word/pad.xml': b'0' * 200_000})
        with mock.patch('documents.upload_validation._OFFICE_RATIO_FLOOR', 1024), \
             mock.patch('documents.upload_validation._OFFICE_RATIO_LIMIT', 5):
            self.assertIn('expands to far more', self.problem('bomb.docx', payload))

    def test_a_type_the_browser_says_is_a_page_or_a_program_is_refused(self):
        for declared in ('text/html', 'application/javascript', 'image/svg+xml',
                         'application/x-msdownload', 'application/x-sh'):
            with self.subTest(declared=declared):
                self.assertIn('not accepted', self.problem('a.pdf', b'%PDF-1.7 body', declared))

    def test_a_client_that_names_no_type_is_not_punished_for_it(self):
        # "text/plain" and "application/octet-stream" are what a client sends when
        # it does not recognise the file; honest uploads arrive that way.
        for declared in ('text/plain', 'application/octet-stream', ''):
            with self.subTest(declared=declared):
                self.assertEqual(self.problem('a.pdf', b'%PDF-1.7 body', declared or None), '')


class BulkUploadTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('val_head', password='pass12345')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()
        self.client.force_login(self.user)

    def post(self, files):
        with mock.patch('documents.jobs._dispatch_job_async'):
            return self.client.post(reverse('documents:bulk_upload'), {'files': files},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json')

    def test_renamed_and_empty_files_are_refused_with_a_reason(self):
        response = self.post([
            SimpleUploadedFile('QATEST_exe_renamed.pdf', b'MZ\x90\x00 program'),
            SimpleUploadedFile('QATEST_zero.pdf', b''),
        ])
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(sorted(data['rejected_filenames']), ['QATEST_exe_renamed.pdf', 'QATEST_zero.pdf'])
        self.assertTrue(any('not a real PDF' in e for e in data['errors']))
        self.assertTrue(any('the file is empty' in e for e in data['errors']))
        self.assertFalse(Document.objects.exists())

    @override_settings(BULK_UPLOAD_MAX_FILES=2)
    def test_files_past_the_cap_are_reported(self):
        files = [SimpleUploadedFile(f'cap_{i}.pdf', f'%PDF-1.4 file {i}'.encode()) for i in range(3)]
        data = self.post(files).json()
        self.assertEqual(data['uploaded_count'], 2)
        self.assertEqual(data['rejected_filenames'], ['cap_2.pdf'])
        self.assertIn('only 2 files are accepted per batch', data['errors'][0])

    def test_a_very_long_name_gives_a_title_that_fits(self):
        self.post([SimpleUploadedFile('R' * 300 + '.pdf', b'%PDF-1.4 long name')])
        doc = Document.objects.get()
        self.assertLessEqual(len(doc.title), 255)
        self.assertLessEqual(len(doc.file.name), 100, 'the stored path fits its column too')


class YearLimitTests(TestCase):

    def test_the_server_refuses_a_year_outside_2000_to_2100(self):
        from documents.forms import DocumentEditForm
        for year, ok in ((99999, False), (-1, False), (1999, False), (2000, True), (2100, True), (2101, False)):
            form = DocumentEditForm(data={'title': 'T', 'year': year})
            self.assertEqual(form.is_valid(), ok, year)
            if not ok:
                self.assertIn('Enter a year between 2000 and 2100.', form.errors['year'])

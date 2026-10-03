"""HTTP tests for document serve, download, and inline view (with real media on disk)."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from documents.models import Document

_TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _write_media_file(relative: str, data: bytes) -> str:
    path = Path(_TEST_MEDIA_ROOT) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(Path(relative)).replace('\\', '/')


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class DocumentHttpFlowTests(TestCase):
    """Upload pipeline assumptions: FileField paths under MEDIA_ROOT."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        rel = 'uploaded_documents/2099/01/flow_test.pdf'
        _write_media_file(rel, b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n')
        cls.doc = Document.objects.create(
            title='Flow Test PDF',
            file=rel,
            file_type='pdf',
            year=2099,
            document_type='Report',
        )
        cls.qa_head = User.objects.create_user('flow_head', 'fh@example.com', 'testpass123')
        cls.qa_head.profile.role = 'qa_staff'
        cls.qa_head.profile.save()

    def setUp(self):
        self.client.login(username='flow_head', password='testpass123')

    def test_document_serve_returns_file(self):
        r = self.client.get(f'/documents/{self.doc.pk}/serve/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/pdf', r.get('Content-Type', ''))

    def test_document_download_returns_attachment(self):
        r = self.client.get(f'/documents/{self.doc.pk}/download/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r.get('Content-Disposition', '').lower())

    def test_document_view_renders(self):
        r = self.client.get(f'/documents/{self.doc.pk}/view/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Flow Test PDF')

    def test_document_edit_panel_loads(self):
        r = self.client.get(f'/documents/{self.doc.pk}/edit/?panel=1')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'qaDocEditForm')
        self.assertContains(r, 'Basic information')
        self.assertNotContains(r, 'Document type')
        self.assertNotContains(r, 'Advanced QA fields')

    def test_document_edit_ajax_post_returns_json(self):
        r = self.client.post(
            f'/documents/{self.doc.pk}/edit/',
            {
                'title': 'Updated Flow Test',
                'year': 2099,
                'program': '',
                'description': 'Updated description.',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['document']['title'], 'Updated Flow Test')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, 'Updated Flow Test')

    def test_docx_preview_returns_pdf(self):
        try:
            from docx import Document as DocxDocument
        except ImportError:
            self.skipTest('python-docx not installed')
        rel = 'uploaded_documents/2099/01/preview_test.docx'
        path = Path(_TEST_MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        docx = DocxDocument()
        docx.add_paragraph('Preview paragraph for QA archive.')
        docx.save(path)
        word_doc = Document.objects.create(
            title='Preview Test DOCX',
            file=rel,
            file_type='docx',
            year=2099,
            document_type='Report',
        )
        r = self.client.get(f'/documents/{word_doc.pk}/preview/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/pdf', r.get('Content-Type', ''))
        body = b''.join(r.streaming_content)
        self.assertTrue(body.startswith(b'%PDF'))

    def test_document_serve_404_when_file_missing(self):
        rel = 'uploaded_documents/2099/01/missing.pdf'
        ghost = Document.objects.create(
            title='Ghost File',
            file=rel,
            file_type='pdf',
            year=2099,
            document_type='Report',
        )
        r = self.client.get(f'/documents/{ghost.pk}/serve/')
        self.assertEqual(r.status_code, 404)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class DocumentDeleteTests(TestCase):
    """Admin delete: missing rows redirect instead of raw 404 (stale UI / double submit)."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        rel = _write_media_file(
            'uploaded_documents/2099/02/del_test.pdf',
            b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n',
        )
        cls.doc = Document.objects.create(
            title='Delete Me',
            file=rel,
            file_type='pdf',
            year=2099,
            document_type='Report',
        )
        cls.admin = User.objects.create_user('del_admin', 'da@example.com', 'testpass123')
        cls.admin.profile.role = 'admin'
        cls.admin.profile.save()

    def setUp(self):
        # A final delete removes the file, and the file system is not rolled
        # back between tests the way the database is.
        _write_media_file('uploaded_documents/2099/02/del_test.pdf',
                          b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n')

    def test_delete_post_missing_pk_redirects_to_repository(self):
        self.client.login(username='del_admin', password='testpass123')
        missing_id = Document.objects.order_by('-pk').first().pk + 1000
        r = self.client.post(f'/documents/{missing_id}/delete/', {})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/documents/repository/')

    def test_delete_post_removes_document(self):
        """
        A single delete is confirmed in a dialog and is then final.

        The row stays, stamped and without its file, so who uploaded and who
        deleted it is still on record; it is out of every listing.
        """
        self.client.login(username='del_admin', password='testpass123')
        pk = self.doc.pk
        r = self.client.post(f'/documents/{pk}/delete/', {})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Document.objects.live().filter(pk=pk).exists())
        doc = Document.objects.deleted().get(pk=pk)
        self.assertIsNotNone(doc.purged_at)
        self.assertEqual(doc.deleted_by.username, 'del_admin')
        self.assertEqual(doc.deletion_batch.kind, 'single')
        self.assertEqual(doc.deletion_batch.status, 'finalized')

    def test_a_single_delete_offers_no_undo(self):
        """The confirmation dialog is the safeguard; there is nothing to undo after it."""
        self.client.login(username='del_admin', password='testpass123')
        pk = self.doc.pk
        self.client.post(f'/documents/{pk}/delete/', {})
        batch = Document.objects.get(pk=pk).deletion_batch
        r = self.client.post(f'/documents/deletions/{batch.pk}/undo/', {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 410)
        self.assertFalse(Document.objects.live().filter(pk=pk).exists())
        self.assertEqual(self.client.get('/documents/deletions/pending/').json()['batches'], [])

    def test_a_single_delete_removes_the_file(self):
        """No orphaned file is left behind once a deletion is final."""
        self.client.login(username='del_admin', password='testpass123')
        path = Path(self.doc.file.path)
        self.assertTrue(path.exists())
        self.client.post(f'/documents/{self.doc.pk}/delete/', {})
        self.assertFalse(path.exists())

    def test_a_get_to_delete_shows_the_confirmation_and_deletes_nothing(self):
        self.client.login(username='del_admin', password='testpass123')
        r = self.client.get(f'/documents/{self.doc.pk}/delete/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Document.objects.live().filter(pk=self.doc.pk).exists())

    def test_bulk_delete_post_removes_selected_documents(self):
        self.client.login(username='del_admin', password='testpass123')
        rel2 = _write_media_file(
            'uploaded_documents/2099/02/del_test_2.pdf',
            b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n',
        )
        doc2 = Document.objects.create(
            title='Delete Me 2',
            file=rel2,
            file_type='pdf',
            year=2099,
            document_type='Report',
        )
        r = self.client.post('/documents/bulk-delete/', {'document_ids': [self.doc.pk, doc2.pk]})
        self.assertEqual(r.status_code, 302)
        # A bulk delete stays undoable for a few seconds: the rows are stamped
        # and out of every listing, and the files are still there for an undo.
        self.assertFalse(Document.objects.live().filter(pk=self.doc.pk).exists())
        self.assertFalse(Document.objects.live().filter(pk=doc2.pk).exists())
        self.assertEqual(Document.objects.deleted().filter(
            pk__in=[self.doc.pk, doc2.pk], purged_at__isnull=True).count(), 2)
        self.assertTrue(Path(self.doc.file.path).exists())

    def test_a_bulk_delete_can_be_undone(self):
        """Undo puts the documents back, files included."""
        self.client.login(username='del_admin', password='testpass123')
        r = self.client.post('/documents/bulk-delete/', {'document_ids': [self.doc.pk]},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(Document.objects.live().filter(pk=self.doc.pk).exists())

        batch_id = r.json()['batch']['id']
        r = self.client.post(f'/documents/deletions/{batch_id}/undo/', {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.json()['restored'], 1)
        self.assertTrue(Document.objects.live().filter(pk=self.doc.pk).exists())
        self.assertIsNone(Document.objects.get(pk=self.doc.pk).deleted_at)
        self.assertTrue(Path(Document.objects.get(pk=self.doc.pk).file.path).exists())

    def test_bulk_delete_post_without_selection_redirects(self):
        self.client.login(username='del_admin', password='testpass123')
        r = self.client.post('/documents/bulk-delete/', {})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/documents/repository/')


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class AreaZipDownloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from qa_structure.models import AccreditationArea

        cls.area2, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'},
        )
        cls.qa_head = User.objects.create_user('zip_qa', 'zip@example.com', 'testpass123')
        cls.qa_head.profile.role = 'qa_staff'
        cls.qa_head.profile.save()

        rel_a = _write_media_file('uploaded_documents/2099/03/a.zip.pdf', b'pdf-a')
        rel_b = _write_media_file('uploaded_documents/2099/03/b.zip.pdf', b'pdf-b')
        Document.objects.create(
            title='Area II Doc',
            file=rel_a,
            file_type='pdf',
            year=2099,
            document_type='Report',
            qa_area='Area II',
            acc_area=cls.area2,
        )
        Document.objects.create(
            title='Unassigned Doc',
            file=rel_b,
            file_type='pdf',
            year=2099,
            document_type='Report',
        )

    def setUp(self):
        self.client.login(username='zip_qa', password='testpass123')

    def test_single_area_zip_download(self):
        import zipfile
        from io import BytesIO

        r = self.client.get('/documents/download/area-zip/?area=Area%20II')
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/zip', r['Content-Type'])
        # Streamed from a temporary file now, not built in memory.
        with zipfile.ZipFile(BytesIO(b''.join(r.streaming_content))) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertFalse(any('/' in n for n in names))

    def test_all_areas_zip_groups_by_folder(self):
        import zipfile
        from io import BytesIO

        r = self.client.get('/documents/download/area-zip/?area=all')
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(BytesIO(b''.join(r.streaming_content))) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.startswith('Area II/') for n in names))
        self.assertTrue(any(n.startswith('Unassigned/') for n in names))

    def test_names_never_collide(self):
        """Two "report.pdf" and a real "report (1).pdf" used to write "report (1).pdf" twice."""
        from documents.views import _unique_arcname
        taken = set()
        names = [_unique_arcname(n, taken) for n in ('report.pdf', 'report.pdf', 'report (1).pdf', 'REPORT.pdf')]
        self.assertEqual(names, ['report.pdf', 'report (1).pdf', 'report (1) (1).pdf', 'REPORT (2).pdf'])
        self.assertEqual(len({n.lower() for n in names}), 4)

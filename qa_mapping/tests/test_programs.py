"""
Tests for QA Programs: seed data, CRUD, repository filter, dashboard.

The checklist-completion and importer cases were removed with the QA checklist
itself. What is tested here is what the programmes still do: tag documents and
drive the Program filter.
"""
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from qa_mapping.models import QAProgram
from documents.models import Document


SEED_CODES = {'ACCRED', 'ISO-EXT', 'ISO-INT', 'BAICS', 'IA', 'PQA'}


def _xlsx_bytes(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class SeedDataTests(TestCase):
    def test_six_default_programs_present(self):
        codes = set(QAProgram.objects.values_list('code', flat=True))
        self.assertEqual(codes & SEED_CODES, SEED_CODES)

class ProgramAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('p_admin', 'a@e.com', 'testpass123')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        self.client.login(username='p_admin', password='testpass123')

    def test_list_renders_seed_programs(self):
        r = self.client.get('/qa-mapping/programs/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ISO-INT')
        self.assertContains(r, 'Accreditation')

    def test_create_program(self):
        r = self.client.post('/qa-mapping/programs/create/', {
            'name': 'Test Program', 'code': 'TEST-X',
            'description': '', 'color': 'hsl(180, 50%, 45%)', 'is_active': 'on',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(QAProgram.objects.filter(code='TEST-X').exists())


class RepositoryProgramFilterTests(TestCase):
    def setUp(self):
        self.qa_head = User.objects.create_user('rep_viewer', 'v@e.com', 'testpass123')
        self.qa_head.profile.role = 'qa_staff'
        self.qa_head.profile.save()
        self.client.login(username='rep_viewer', password='testpass123')

        iso = QAProgram.objects.get(code='ISO-INT')
        accred = QAProgram.objects.get(code='ACCRED')
        self.iso_doc = Document.objects.create(
            title='ISO doc', file='uploaded_documents/iso.pdf', file_type='pdf',
            year=2026, document_type='Doc', program=iso,
        )
        self.accred_doc = Document.objects.create(
            title='Accred doc', file='uploaded_documents/acc.pdf', file_type='pdf',
            year=2026, document_type='Doc', program=accred,
        )

    def test_filter_by_program(self):
        iso = QAProgram.objects.get(code='ISO-INT')
        r = self.client.get(f'/documents/repository/?program={iso.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ISO doc')
        self.assertNotContains(r, 'Accred doc')

    def test_no_filter_shows_both(self):
        r = self.client.get('/documents/repository/')
        self.assertContains(r, 'ISO doc')
        self.assertContains(r, 'Accred doc')


class BulkUploadProgramTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('bu_staff', 'b@e.com', 'testpass123')
        self.staff.profile.role = 'qa_staff'
        self.staff.profile.save()
        self.client.login(username='bu_staff', password='testpass123')

    def test_bulk_upload_tags_program(self):
        prog = QAProgram.objects.get(code='IA')
        upload = SimpleUploadedFile('memo.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')
        r = self.client.post('/documents/bulk-upload/', {
            'files': upload,
            'program': str(prog.pk),
        })
        self.assertEqual(r.status_code, 302)
        doc = Document.objects.first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.program_id, prog.pk)


class DashboardProgramOverviewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('d_admin', 'd@e.com', 'testpass123')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        self.client.login(username='d_admin', password='testpass123')

    def test_dashboard_renders_simplified_layout_and_program_filter(self):
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'At a glance')
        self.assertContains(r, 'Overview')
        self.assertContains(r, 'Upload Activity')
        self.assertContains(r, 'File Formats')
        self.assertContains(r, 'Duplicates to Review')
        self.assertContains(r, 'All QA Documents (Combined)')
        self.assertNotContains(r, 'Evidence Ready')
        self.assertNotContains(r, 'Operational Alerts')
        self.assertNotContains(r, 'Breakdown')
        # The Quick Actions tiles were removed: every destination they linked to
        # (Upload, Repository, Smart Search) already has a permanent sidebar entry.
        self.assertNotContains(r, 'Quick Actions')

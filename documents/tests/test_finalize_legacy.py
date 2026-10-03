"""
`finalize_deletions --include-legacy`: deletions made before batches existed.

The earlier version stamped `deleted_at` and kept the file indefinitely. The
command removes those files on request -- never implicitly -- and keeps the
rows and their history, like any other permanent deletion.
"""
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from documents.models import ActivityLog, Document

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class LegacyDeletionTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def make(self, name, deleted):
        rel = f'uploaded_documents/legacy/{name}.pdf'
        path = Path(MEDIA) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'%PDF-1.4\n%%EOF\n')
        doc = Document.objects.create(title=name, file=rel, file_type='pdf', year=2026,
                                      document_type='Report', uploaded_by=self.owner)
        if deleted:
            Document.objects.filter(pk=doc.pk).update(deleted_at=timezone.now())
        return doc, path

    def setUp(self):
        self.owner = User.objects.create_user('legacy_owner', 'l@test.com', 'pass12345')

    def test_plain_run_leaves_legacy_deletions_alone(self):
        doc, path = self.make('old_deleted', deleted=True)
        call_command('finalize_deletions', stdout=StringIO())
        self.assertTrue(path.exists())
        self.assertIsNone(Document.objects.get(pk=doc.pk).purged_at)

    def test_include_legacy_removes_the_files_and_keeps_the_records(self):
        gone, gone_path = self.make('old_deleted', deleted=True)
        kept, kept_path = self.make('still_live', deleted=False)
        out = StringIO()
        call_command('finalize_deletions', '--include-legacy', stdout=out)
        self.assertIn('Removed the files of 1 earlier deletion', out.getvalue())
        self.assertFalse(gone_path.exists())
        self.assertTrue(kept_path.exists())
        gone.refresh_from_db()
        self.assertIsNotNone(gone.purged_at)
        self.assertEqual(gone.original_filename, 'old_deleted.pdf')
        self.assertTrue(ActivityLog.objects.filter(document=gone, action='purge_document').exists())
        self.assertIsNone(Document.objects.get(pk=kept.pk).deleted_at)

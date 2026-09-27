"""
Backfill Document.content_sha256 for rows uploaded before the column existed.

Best-effort: a missing or unreadable file simply leaves the hash empty, and
Document.ensure_content_hash() will fill it in later on demand.
"""
import hashlib
import os

from django.db import migrations


def _sha256(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def backfill(apps, schema_editor):
    Document = apps.get_model('documents', 'Document')
    for doc in Document.objects.filter(content_sha256='').iterator():
        if not doc.file:
            continue
        try:
            path = doc.file.path
        except (ValueError, NotImplementedError):
            continue
        if not os.path.exists(path):
            continue
        try:
            digest = _sha256(path)
        except OSError:
            continue
        Document.objects.filter(pk=doc.pk).update(content_sha256=digest)


def noop(apps, schema_editor):
    """Reversing just drops the cached hashes with the column; nothing to undo."""


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0010_document_content_sha256'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]

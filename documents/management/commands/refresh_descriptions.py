"""Re-build document descriptions from extracted text using improved heuristics."""
from django.core.management.base import BaseCommand

from documents.auto_metadata import build_description
from documents.models import Document


class Command(BaseCommand):
    help = 'Refresh auto-generated descriptions for documents that have extracted text.'

    def handle(self, *args, **options):
        updated = 0
        for doc in Document.objects.all().iterator():
            text = doc.combined_text
            if not text:
                continue
            new_desc = build_description(
                text,
                title=doc.title,
                document_type=doc.document_type,
                filename=doc.file.name if doc.file else '',
            )
            if new_desc and new_desc != doc.description:
                doc.description = new_desc
                doc.save(update_fields=['description'])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f'Updated description on {updated} document(s).'))

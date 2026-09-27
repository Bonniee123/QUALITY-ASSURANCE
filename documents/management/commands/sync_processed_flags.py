"""Mark is_processed=True for documents that already have extracted text but a stale flag."""
from django.core.management.base import BaseCommand
from django.db.models import Q

from documents.models import Document


class Command(BaseCommand):
    help = 'Set is_processed=True on documents whose ingest clearly finished but flag was never set.'

    def handle(self, *args, **options):
        qs = Document.objects.filter(is_processed=False).filter(
            Q(extracted_text__gt='') | Q(ocr_text__gt='')
        )
        count = qs.update(is_processed=True)
        self.stdout.write(self.style.SUCCESS(f'Updated is_processed on {count} document(s).'))

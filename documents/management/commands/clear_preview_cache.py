"""Delete cached DOCX→PDF preview files (e.g. after upgrading converters)."""
from django.core.management.base import BaseCommand

from documents.models import Document
from documents.preview_service import clear_preview_cache


class Command(BaseCommand):
    help = 'Clear cached PDF previews so documents re-render with the latest converter.'

    def add_arguments(self, parser):
        parser.add_argument('--document-id', type=int, help='Clear cache for one document only')

    def handle(self, *args, **options):
        doc_id = options.get('document_id')
        if doc_id:
            doc = Document.objects.filter(pk=doc_id).first()
            if not doc:
                self.stderr.write(self.style.ERROR(f'Document #{doc_id} not found.'))
                return
            clear_preview_cache(doc)
            self.stdout.write(self.style.SUCCESS(f'Cleared preview cache for document #{doc_id}.'))
        else:
            clear_preview_cache()
            self.stdout.write(self.style.SUCCESS('Cleared all cached document previews.'))

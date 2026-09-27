from django.core.management.base import BaseCommand

from documents.jobs import _reprocess_ocr


class Command(BaseCommand):
    help = 'Reprocess OCR for documents.'

    def add_arguments(self, parser):
        parser.add_argument('--only-empty', action='store_true', help='Only reprocess documents with empty OCR text.')
        parser.add_argument('--pdf-only', action='store_true', help='Only reprocess PDF documents.')

    def handle(self, *args, **options):
        msg = _reprocess_ocr({
            'only_empty': bool(options.get('only_empty')),
            'pdf_only': bool(options.get('pdf_only')),
        })
        self.stdout.write(self.style.SUCCESS(str(msg)))

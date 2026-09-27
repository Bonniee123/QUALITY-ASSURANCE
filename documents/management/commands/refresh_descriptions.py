"""Re-build document descriptions from extracted text using improved heuristics."""
from django.core.management.base import BaseCommand

from documents.auto_metadata import build_description, extract_metadata_from_filename
from documents.models import Document


class Command(BaseCommand):
    help = 'Refresh auto-generated descriptions for documents that have extracted text.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--spreadsheets-only', action='store_true',
            help='Only XLSX files, whose descriptions used to be their column headings. '
                 'Leaves every other description, including hand-edited ones, untouched.')

    def handle(self, *args, **options):
        updated = 0
        docs = Document.objects.all()
        if options['spreadsheets_only']:
            docs = docs.filter(file_type__in=['xlsx', 'xls', 'xlsm'])
        for doc in docs.iterator():
            text = doc.combined_text
            if not text:
                continue
            if options['spreadsheets_only']:
                self._retitle_from_file_name(doc, text)
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

    @staticmethod
    def _retitle_from_file_name(doc, text):
        """A title that is exactly the sheet's first row came from its column headings, not a person."""
        first_row = next((line.strip() for line in text.splitlines() if line.strip()), '')
        # Automatic titles are the first row cut at 150 characters (_title_from_text).
        if doc.title.strip() == first_row[:150].strip() and doc.file:
            name = extract_metadata_from_filename(doc.file.name.rsplit('/', 1)[-1])['title']
            if name:
                doc.title = name
                doc.save(update_fields=['title'])

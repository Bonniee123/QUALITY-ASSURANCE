import os

from django.core.management.base import BaseCommand

from documents.models import Document
from ai_processing.image_hash import is_image_file, compute_image_hash


class Command(BaseCommand):
    help = 'Compute and store perceptual hashes (dHash) for image documents that lack one.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Recompute hashes for every image document, not just those missing one.',
        )

    def handle(self, *args, **options):
        recompute_all = options['all']
        qs = Document.objects.all()
        updated = 0
        skipped = 0
        for doc in qs:
            if not is_image_file(doc.file_type):
                continue
            if doc.image_phash and not recompute_all:
                continue
            if not doc.file or not hasattr(doc.file, 'path') or not os.path.exists(doc.file.path):
                skipped += 1
                continue
            phash = compute_image_hash(doc.file.path)
            if phash and phash != doc.image_phash:
                doc.image_phash = phash
                doc.save(update_fields=['image_phash'])
                updated += 1
            elif not phash:
                skipped += 1
        self.stdout.write(self.style.SUCCESS(
            f'Image hashes computed: {updated} updated, {skipped} skipped (missing file or unreadable).'
        ))

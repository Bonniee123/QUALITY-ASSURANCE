"""Make expired bulk deletions permanent (removes their files; keeps their records and history)."""
from django.core.management.base import BaseCommand

from documents.deletion import finalize_expired_batches, finalize_legacy_deletions


class Command(BaseCommand):
    help = ('Finalize bulk deletions whose undo window has passed. The live-update poll already does '
            'this while anyone has the system open; schedule this command for when nobody does.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--include-legacy', action='store_true',
            help='Also remove the files of documents deleted before deletion batches existed '
                 '(they were kept indefinitely). Their records and history stay.',
        )

    def handle(self, *args, **options):
        done = finalize_expired_batches()
        self.stdout.write(self.style.SUCCESS(f'Finalized {done} deletion batch(es).'))
        if options['include_legacy']:
            legacy = finalize_legacy_deletions()
            self.stdout.write(self.style.SUCCESS(f'Removed the files of {legacy} earlier deletion(s).'))

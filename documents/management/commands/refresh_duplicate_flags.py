from django.core.management.base import BaseCommand

from documents.jobs import _refresh_duplicate_flags


class Command(BaseCommand):
    help = 'Refresh duplicate flags for all active documents.'

    def handle(self, *args, **options):
        msg = _refresh_duplicate_flags()
        self.stdout.write(self.style.SUCCESS(str(msg)))

from django.core.management.base import BaseCommand

from documents.jobs import _reindex_search_artifacts


class Command(BaseCommand):
    help = 'Recompute search artifacts (TF-IDF keywords) for documents.'

    def handle(self, *args, **options):
        msg = _reindex_search_artifacts()
        self.stdout.write(self.style.SUCCESS(str(msg)))

from django.core.management.base import BaseCommand

from documents.jobs import run_job
from documents.models import BackgroundJob


class Command(BaseCommand):
    help = 'Run pending background jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process current pending jobs once and exit.')
        parser.add_argument('--limit', type=int, default=20, help='Max jobs to process in one run.')

    def handle(self, *args, **options):
        limit = max(1, int(options.get('limit') or 20))
        count = 0
        jobs = BackgroundJob.objects.filter(status='pending').order_by('created_at')[:limit]
        for job in jobs:
            run_job(job)
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Processed {count} background job(s).'))

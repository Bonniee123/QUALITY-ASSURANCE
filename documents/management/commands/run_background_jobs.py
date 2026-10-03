import threading
import time

from django.core.management.base import BaseCommand

from documents.jobs import recover_interrupted_jobs, run_job
from documents.models import BackgroundJob

# Job workers are daemon threads, so the interpreter does not wait for them.
# A bulk upload asks for an analysis run when it finishes, and that run happens
# on a thread of its own -- which this process would kill by returning, leaving
# the new job stuck on 'running' and its documents unclustered.
WORKER_THREAD_PREFIX = 'qa-'


class Command(BaseCommand):
    help = 'Run pending background jobs, including any a restart left half-finished.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process current pending jobs once and exit.')
        parser.add_argument('--limit', type=int, default=20, help='Max jobs to process in one run.')
        parser.add_argument(
            '--keep-stale', action='store_true',
            help='Leave jobs marked running as they are, instead of re-queueing them.',
        )

    def handle(self, *args, **options):
        limit = max(1, int(options.get('limit') or 20))

        # Jobs run on threads inside the web server. When that process dies or
        # its thread stops, the row stays 'running' for ever and its documents
        # sit on "Processing" with no cluster and no keywords. The web server
        # re-queues those at start-up, but this command -- the one a person
        # reaches for precisely because the queue is stuck -- only looked at
        # 'pending', so it reported "Processed 0 background job(s)" and left
        # the stuck batch exactly where it was.
        #
        # Every job type is safe to run again: text extraction skips files that
        # already have text, and the analysis pipeline recomputes what it
        # writes. Use --keep-stale when a live server may still be working on
        # them and you only want the pending queue drained.
        recovered = 0
        if not options.get('keep_stale'):
            recovered = recover_interrupted_jobs()
            if recovered:
                self.stdout.write(f'Re-queued {recovered} interrupted job(s).')

        count = 0
        jobs = BackgroundJob.objects.filter(status='pending').order_by('created_at')[:limit]
        for job in jobs:
            run_job(job)
            count += 1

        followed = self._wait_for_workers()
        if followed:
            self.stdout.write(f'Waited for {followed} follow-up worker(s) to finish.')
        self.stdout.write(self.style.SUCCESS(f'Processed {count} background job(s).'))

    def _wait_for_workers(self, timeout=3600):
        """Block until the job threads this process started have finished."""
        waited_for = 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            workers = [
                t for t in threading.enumerate()
                if t.is_alive() and t is not threading.current_thread()
                and t.name.startswith(WORKER_THREAD_PREFIX)
            ]
            if not workers:
                return waited_for
            waited_for += 1
            workers[0].join(timeout=max(1.0, min(30.0, deadline - time.monotonic())))
        self.stderr.write('Gave up waiting for a job worker; it is still running.')
        return waited_for

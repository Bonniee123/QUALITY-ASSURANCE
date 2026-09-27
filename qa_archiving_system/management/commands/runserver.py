"""
Development server with one-command startup.

`python manage.py runserver` will:
  - apply migrations when the database is not ready
  - create the default admin account if missing (admin / admin123)
  - resume any pending background jobs in a daemon thread
"""
import os
import threading

from django.core.management import call_command
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserverCommand,
)


def ensure_database_ready(stdout, style):
    from django.contrib.auth.models import User
    from django.db import connection

    db_ready = True
    try:
        connection.ensure_connection()
        User.objects.exists()
    except Exception:
        db_ready = False

    if not db_ready:
        stdout.write(style.WARNING('Database not ready — applying migrations...'))
        call_command('migrate', interactive=False, verbosity=1)

    if not User.objects.filter(username='admin').exists():
        stdout.write(style.WARNING('Creating default admin account (admin / admin123)...'))
        call_command('create_default_admin', verbosity=1)


def start_pending_job_worker(use_reloader=True):
    """
    Resume interrupted background jobs without a separate worker process.

    With the autoreloader, the first process only watches files and the child it
    starts (RUN_MAIN=true) serves requests, so that child is the one to resume
    jobs. With --noreload there is only one process -- it never had RUN_MAIN
    set, so jobs were never resumed and a batch cut off by a restart stayed
    "running" for good.
    """
    if use_reloader and os.environ.get('RUN_MAIN') != 'true':
        return

    def worker():
        try:
            from documents.jobs import resume_pending_jobs

            count = resume_pending_jobs()
            if count:
                print(f'[QA Archive] Resumed {count} pending background job(s).')
        except Exception as exc:
            print(f'[QA Archive] Could not resume pending jobs: {exc}')

    threading.Thread(target=worker, name='qa-pending-jobs', daemon=True).start()


class Command(StaticfilesRunserverCommand):
    help = (
        'Starts the development server and prepares the local environment '
        '(migrations, default admin, pending background jobs).'
    )

    def handle(self, *args, **options):
        ensure_database_ready(self.stdout, self.style)
        start_pending_job_worker(options.get('use_reloader', True))
        if os.environ.get('RUN_MAIN') == 'true':
            from django.conf import settings
            if not settings.DEBUG:
                self.stdout.write(self.style.WARNING(
                    'WARNING: DEBUG is False — local pages may fail. '
                    'Run scripts\\reset_dev_env.ps1 or use a fresh terminal.'
                ))
            self.stdout.write(
                self.style.SUCCESS(
                    'QA Archiving System ready — open http://127.0.0.1:8000/ '
                    '(default admin: admin / admin123)'
                )
            )
        super().handle(*args, **options)

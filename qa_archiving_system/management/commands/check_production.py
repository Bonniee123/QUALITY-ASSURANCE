"""
Validate production deployment settings.

Usage:
    DEBUG=False SECRET_KEY=... ALLOWED_HOSTS=qa.example.edu python manage.py check_production
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Verify production security settings before go-live'

    def handle(self, *args, **options):
        issues = []
        warnings = []

        if settings.DEBUG:
            issues.append('DEBUG is True — set DEBUG=False in production.')

        default_key = 'django-insecure-qa-archive-dev-key-change-in-production-2024'
        if settings.SECRET_KEY == default_key:
            issues.append('SECRET_KEY is still the development default.')

        hosts = set(settings.ALLOWED_HOSTS)
        if hosts <= {'127.0.0.1', 'localhost'}:
            issues.append('ALLOWED_HOSTS is localhost-only — set your real hostname(s).')

        if not settings.USE_TLS and not getattr(settings, 'TRUST_X_FORWARDED_SSL', False):
            warnings.append('USE_TLS is False — enable HTTPS (USE_TLS=true) for production.')

        if not getattr(settings, 'CSRF_TRUSTED_ORIGINS', None) and settings.USE_TLS:
            warnings.append(
                'CSRF_TRUSTED_ORIGINS is empty — set e.g. CSRF_TRUSTED_ORIGINS=https://your-host'
            )

        # The system runs on MySQL only; settings.py refuses to start on
        # anything else, so reaching this branch means the configuration was
        # changed by hand and is worth reporting rather than assuming.
        db_engine = settings.DATABASES['default']['ENGINE']
        if 'mysql' not in db_engine:
            warnings.append(
                'Database engine is %s — this system is configured for MySQL only.'
                % db_engine
            )

        if settings.DEBUG:
            warnings.append(
                'DEBUG=True is development mode (Django serves static files, keeps SQL logs in memory, and '
                'SHOW_DEBUG_ERROR_PAGES would expose tracebacks) — disable in production. '
                '(/media/ is blocked either way; documents are served only through signed-in views.)'
            )

        for item in warnings:
            self.stdout.write(self.style.WARNING(f'WARNING: {item}'))

        if issues:
            for item in issues:
                self.stderr.write(self.style.ERROR(f'BLOCKER: {item}'))
            raise CommandError(f'{len(issues)} production blocker(s) found.')

        self.stdout.write(self.style.SUCCESS(
            'Production check passed.'
            + (f' ({len(warnings)} warning(s) — review above.)' if warnings else '')
        ))

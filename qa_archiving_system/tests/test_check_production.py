"""Tests for the check_production management command."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


@override_settings(
    DEBUG=False,
    SECRET_KEY='x' * 50,
    ALLOWED_HOSTS=['qa.example.edu'],
    USE_TLS=True,
    CSRF_TRUSTED_ORIGINS=['https://qa.example.edu'],
)
class CheckProductionCommandTests(TestCase):
    def test_passes_with_valid_production_settings(self):
        out = StringIO()
        call_command('check_production', stdout=out)
        self.assertIn('Production check passed', out.getvalue())

    @override_settings(DEBUG=True)
    def test_fails_when_debug_enabled(self):
        with self.assertRaises(CommandError):
            call_command('check_production')

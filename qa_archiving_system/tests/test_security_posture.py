"""
The protections that were only ever true by reading the code.

Everything here was correct before this file existed -- password hashing, the
session key changing at sign-in, the cookie flags, the frame header, file names
that cannot climb out of the upload folder, the refusal to start with a
development key in production, and the HTTPS switch. None of it was *checked* by
anything, so a later change could have taken any of it away in silence. These
tests hold those properties in place.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.base import ContentFile
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

BASE_DIR = Path(settings.BASE_DIR)
APP_DIRS = ('accounts', 'ai_processing', 'chatbot', 'dashboard', 'documents', 'messaging',
            'notifications', 'qa_archiving_system', 'qa_mapping', 'qa_structure', 'reports', 'search')


def _app_sources(skip_migrations=False):
    for app in APP_DIRS:
        for path in (BASE_DIR / app).rglob('*.py'):
            if skip_migrations and 'migrations' in path.parts:
                continue
            yield path


def _production_settings(**env_overrides):
    """Read settings back from a fresh process started with these env vars."""
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    env.update(env_overrides)
    # The probe reads security settings, not the database. It used to remove
    # MYSQL_DATABASE so the old SQLite fallback would be used, but that fallback
    # no longer exists and settings.py refuses to load without the variable, so
    # a value is supplied instead. No connection is ever opened.
    env.setdefault('MYSQL_DATABASE', 'qa_archive')
    code = (
        'import json;from django.conf import settings;'
        'print("PROBE:" + json.dumps({'
        '"debug": settings.DEBUG,'
        '"ssl_redirect": getattr(settings, "SECURE_SSL_REDIRECT", False),'
        '"session_secure": getattr(settings, "SESSION_COOKIE_SECURE", False),'
        '"csrf_secure": getattr(settings, "CSRF_COOKIE_SECURE", False),'
        '"hsts": getattr(settings, "SECURE_HSTS_SECONDS", 0),'
        '"nosniff": getattr(settings, "SECURE_CONTENT_TYPE_NOSNIFF", False),'
        '"referrer": getattr(settings, "SECURE_REFERRER_POLICY", ""),'
        '"httponly": getattr(settings, "SESSION_COOKIE_HTTPONLY", False),'
        '"samesite": getattr(settings, "SESSION_COOKIE_SAMESITE", ""),'
        '"csrf_origins": list(getattr(settings, "CSRF_TRUSTED_ORIGINS", []))'
        '}))'
    )
    return subprocess.run([sys.executable, 'manage.py', 'shell', '-c', code],
                          cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=180)


class PasswordStorageTests(TestCase):

    def test_a_password_is_stored_only_as_a_salted_hash(self):
        user = User.objects.create_user('hash_probe', 'h@example.com', 'Str0ng-Passw0rd!')
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'), user.password[:24])
        self.assertNotIn('Str0ng-Passw0rd!', user.password)
        self.assertTrue(user.check_password('Str0ng-Passw0rd!'))

    def test_two_accounts_with_the_same_password_do_not_share_a_hash(self):
        """A shared hash would mean no salt: one cracked password would open both."""
        first = User.objects.create_user('salt_a', 'a@example.com', 'Str0ng-Passw0rd!')
        second = User.objects.create_user('salt_b', 'b@example.com', 'Str0ng-Passw0rd!')
        self.assertNotEqual(first.password, second.password)

    def test_a_weak_password_is_refused_by_the_user_form(self):
        from accounts.forms import UserCreateForm
        form = UserCreateForm(data={
            'username': 'weakling', 'first_name': 'Weak', 'last_name': 'Choice',
            'email': 'w@example.com', 'role': 'faculty', 'department': 'QA Office',
            'status': 'active', 'password': '12345678', 'confirm_password': '12345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)


class SessionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('sess_probe', 's@example.com', 'Str0ng-Passw0rd!')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()

    def test_the_session_key_changes_at_sign_in(self):
        """Otherwise an attacker who plants a session id keeps it after you log in."""
        client = Client()
        session = client.session
        session['probe'] = 1
        session.save()
        before = session.session_key

        client.post(reverse('accounts:login'),
                    {'username': 'sess_probe', 'password': 'Str0ng-Passw0rd!'})
        self.assertIsNotNone(client.session.session_key)
        self.assertNotEqual(client.session.session_key, before)

    def test_the_session_cookie_is_closed_to_scripts(self):
        client = Client()
        client.post(reverse('accounts:login'),
                    {'username': 'sess_probe', 'password': 'Str0ng-Passw0rd!'})
        cookie = client.cookies['sessionid']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(str(cookie['samesite']).lower(), 'lax')


class ResponseHeaderTests(TestCase):

    def test_pages_refuse_to_be_framed(self):
        response = Client().get(reverse('accounts:login'))
        self.assertEqual(response.headers.get('X-Frame-Options'), 'SAMEORIGIN')


class StoredFileNameTests(TestCase):

    def test_a_file_name_cannot_climb_out_of_the_upload_folder(self):
        from documents.models import Document
        document = Document(title='probe', file_type='pdf', year=2026, document_type='Report')
        with self.assertRaises(SuspiciousFileOperation):
            document.file.save('../../evil.pdf', ContentFile(b'%PDF-1.4'), save=False)

    def test_a_name_that_is_only_dots_is_refused(self):
        from documents.models import Document
        document = Document(title='probe', file_type='pdf', year=2026, document_type='Report')
        with self.assertRaises(SuspiciousFileOperation):
            document.file.save('..', ContentFile(b'%PDF-1.4'), save=False)


class OutputEscapingTests(TestCase):
    """Stored text must reach the page as text, never as markup."""

    def setUp(self):
        self.admin = User.objects.create_user('xss_probe', 'x@example.com', 'Str0ng-Passw0rd!')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        self.client.force_login(self.admin)

    def test_a_script_tag_in_a_document_title_is_shown_not_run(self):
        from documents.models import Document
        Document.objects.create(title='<script>alert("xss")</script>', file='uploaded_documents/x.pdf',
                                file_type='pdf', year=2026, document_type='Report')
        body = self.client.get(reverse('documents:repository')).content.decode()
        self.assertNotIn('<script>alert("xss")</script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_search_highlighting_escapes_before_it_marks(self):
        """The one filter that outputs HTML: it escapes first, then wraps matches."""
        from search.templatetags.search_extras import highlight_terms
        out = str(highlight_terms('<script>alert(1)</script> retention policy', 'policy'))
        self.assertNotIn('<script>', out)
        self.assertIn('&lt;script&gt;', out)
        self.assertIn('<mark class="srch-hl">policy</mark>', out)


class SourceGuardTests(SimpleTestCase):
    """Properties that hold because of how the code is written, kept that way."""

    def test_no_external_command_is_run_through_a_shell(self):
        offenders = [str(p.relative_to(BASE_DIR)) for p in _app_sources()
                     if re.search(r'shell\s*=\s*True|os\.system\(|os\.popen\(', p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [], f'a shell call would let a file name carry a command: {offenders}')

    def test_no_query_is_assembled_by_hand(self):
        pattern = re.compile(r'\.raw\(|cursor\.execute\(|connection\.cursor\(')
        offenders = [str(p.relative_to(BASE_DIR)) for p in _app_sources(skip_migrations=True)
                     if pattern.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [], f'raw SQL outside a migration invites injection: {offenders}')

    def test_nothing_uploaded_is_ever_executed(self):
        pattern = re.compile(r'\beval\(|\bexec\(|pickle\.loads?\(|subprocess\.[A-Za-z_]+\([^)]*doc\.file')
        offenders = [str(p.relative_to(BASE_DIR)) for p in _app_sources()
                     if pattern.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [], f'uploaded content must never reach an interpreter: {offenders}')


class ProductionSettingsTests(SimpleTestCase):
    """
    The deployment switches, read out of a real process.

    settings.py decides these at import time, so overriding DEBUG inside a test
    proves nothing; each case starts Django again with the environment a
    deployment would have.
    """

    def _probe(self, result):
        line = next((ln for ln in result.stdout.splitlines() if ln.startswith('PROBE:')), '')
        self.assertTrue(line, f'no probe output. stdout={result.stdout[-400:]} stderr={result.stderr[-400:]}')
        return json.loads(line[len('PROBE:'):])

    def test_production_refuses_to_start_on_the_development_key(self):
        result = _production_settings(DEBUG='False', ALLOWED_HOSTS='qa.example.edu',
                                      SECRET_KEY='django-insecure-qa-archive-dev-key-change-in-production-2024')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SECRET_KEY', result.stderr)

    def test_production_refuses_a_localhost_only_host_list(self):
        result = _production_settings(DEBUG='False', SECRET_KEY='x' * 60, ALLOWED_HOSTS='127.0.0.1,localhost')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ALLOWED_HOSTS', result.stderr)

    def test_turning_on_tls_turns_on_every_https_protection(self):
        result = _production_settings(DEBUG='False', SECRET_KEY='x' * 60,
                                      ALLOWED_HOSTS='qa.example.edu', USE_TLS='true')
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        probe = self._probe(result)
        self.assertFalse(probe['debug'])
        self.assertTrue(probe['ssl_redirect'], 'HTTP should be redirected to HTTPS')
        self.assertTrue(probe['session_secure'], 'the session cookie should be HTTPS-only')
        self.assertTrue(probe['csrf_secure'], 'the CSRF cookie should be HTTPS-only')
        self.assertGreaterEqual(probe['hsts'], 31536000, 'HSTS should be a year or more')
        self.assertTrue(probe['nosniff'])
        self.assertEqual(probe['referrer'], 'same-origin')
        self.assertTrue(probe['httponly'])
        self.assertEqual(probe['samesite'], 'Lax')
        self.assertIn('https://qa.example.edu', probe['csrf_origins'])

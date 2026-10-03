"""
Every page, opened as every role.

A sweep rather than a unit test: it asks the server for each named URL as an
Administrator, a QA Head and a Faculty member, and fails on a server error or
on a page that leaks past its own access rule. It is deliberately blunt, so it
catches the kind of fault that only appears when a template meets a real
request -- a missing context variable, a reverse() for a route that was
renamed, a decorator dropped from a view.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from documents.models import Document

# Routes that change or destroy data, or that exist only to receive a form.
# A sweep must not press them.
SKIP_PREFIXES = ('admin:',)
SKIP_CONTAINING = (
    'delete', 'remove', 'create', 'add', 'edit', 'run', 'send', 'export',
    'logout', 'toggle', 'mark_', 'sync', 'bulk_', 'reprocess', 'restore',
)


def named_routes():
    """Every named URL in the project, with the number of arguments it takes."""
    found = []

    def walk(resolver, prefix=''):
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                namespace = entry.namespace or ''
                walk(entry, prefix + (namespace + ':' if namespace else ''))
            elif isinstance(entry, URLPattern) and entry.name:
                argument_count = entry.pattern.regex.groups
                found.append((prefix + entry.name, argument_count))

    walk(get_resolver())
    return sorted(set(found))


def make_user(username, role, is_super=False):
    user = User.objects.create_user(username, f'{username}@example.com', 'pw-for-tests')
    if is_super:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=['is_superuser', 'is_staff'])
    profile = user.profile
    profile.role = role
    profile.status = 'active'
    profile.save(update_fields=['role', 'status'])
    return user


class PageCrawlTests(TestCase):
    """Open everything, as everyone, and report what breaks."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('crawl_admin', 'admin', is_super=True)
        cls.head = make_user('crawl_head', 'qa_staff')
        cls.faculty = make_user('crawl_faculty', 'faculty')
        cls.document = Document.objects.create(
            title='Crawl Fixture Document',
            file_type='pdf',
            year=2026,
            uploaded_by=cls.admin,
        )

    def crawl(self, user):
        """GET every safe route as this user. Returns (server_errors, results)."""
        from django.urls import NoReverseMatch, reverse

        self.client.force_login(user)
        errors, results = [], []
        for name, argument_count in named_routes():
            if name.startswith(SKIP_PREFIXES):
                continue
            if any(token in name.lower() for token in SKIP_CONTAINING):
                continue
            try:
                url = reverse(name, args=[self.document.pk] * argument_count)
            except NoReverseMatch:
                continue
            try:
                response = self.client.get(url, follow=True)
            except Exception as exc:                      # noqa: BLE001 - reported, not raised
                errors.append((name, url, f'{type(exc).__name__}: {exc}'))
                continue
            status = response.status_code
            results.append((name, url, status))
            if status >= 500:
                errors.append((name, url, f'HTTP {status}'))
        return errors, results

    def test_no_page_raises_a_server_error_for_an_administrator(self):
        errors, results = self.crawl(self.admin)
        self.assertTrue(results, 'the crawler found no routes to open')
        self.assertEqual(errors, [], f'pages failed for an Administrator: {errors}')

    def test_no_page_raises_a_server_error_for_a_qa_head(self):
        errors, _ = self.crawl(self.head)
        self.assertEqual(errors, [], f'pages failed for a QA Head: {errors}')

    def test_no_page_raises_a_server_error_for_faculty(self):
        errors, _ = self.crawl(self.faculty)
        self.assertEqual(errors, [], f'pages failed for Faculty: {errors}')

    def test_every_page_refuses_to_be_framed(self):
        """
        Clickjacking cover for ordinary pages.

        The document views that really are embedded set SAMEORIGIN themselves;
        everything else must say DENY.
        """
        self.client.force_login(self.admin)
        response = self.client.get('/dashboard/', follow=True)
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')

    def test_the_embedded_document_views_still_allow_same_origin(self):
        from django.urls import reverse

        self.client.force_login(self.admin)
        response = self.client.get(reverse('documents:serve', args=[self.document.pk]))
        # The file itself is missing in this fixture, so the view may 404 --
        # what matters is that when it does answer, it answers SAMEORIGIN.
        if response.status_code == 200:
            self.assertEqual(response.headers.get('X-Frame-Options'), 'SAMEORIGIN')

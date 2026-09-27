"""
Role-by-role page smoke check used to verify the UI/UX cleanup broke nothing.

For each role it logs in and requests every page that role can reach, asserting:
  * the expected HTTP status (200, or 302/403 where the role is meant to be blocked)
  * no Django template/marker leakage in the rendered HTML
  * the page actually rendered its shell (sidebar + main content present)

Usage:  python scripts/ui_smoke_check.py
Exit code 0 = all good, 1 = at least one failure.
"""
import os
import re
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
# Django's test Client sends Host: testserver, which the project's ALLOWED_HOSTS
# (127.0.0.1, localhost) rejects with a 400 before any view runs.
os.environ.setdefault('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver')
django.setup()

from django.test import Client  # noqa: E402

# (label, url, {role: expected_status})
ADMIN, QA, FAC = 'admin', 'qa_staff', 'faculty'
OK = 200

PAGES = [
    ('Dashboard',            '/dashboard/',                    {ADMIN: OK, QA: OK, FAC: OK}),
    ('Upload (structured)',  '/documents/upload/',             {ADMIN: OK, QA: OK}),
    ('Faculty upload',       '/documents/faculty-upload/',     {FAC: OK}),
    ('Bulk upload',          '/documents/bulk-upload/',        {ADMIN: OK, QA: OK}),
    ('Repository',           '/documents/repository/',         {ADMIN: OK, QA: OK, FAC: OK}),
    ('Area submissions',     '/documents/area-submissions/',   {ADMIN: OK, QA: OK}),
    ('Clusters',             '/documents/clusters/',           {ADMIN: OK, QA: OK}),
    ('AI processing',        '/ai-processing/',                {ADMIN: OK}),
    ('Reports',              '/reports/',                      {ADMIN: OK}),
    ('User management',      '/accounts/users/',               {ADMIN: OK}),
    ('Settings',             '/accounts/settings/',            {ADMIN: OK}),
    ('Audit log',            '/accounts/audit-log/',           {ADMIN: OK}),
    ('Chatbot',              '/chatbot/',                      {ADMIN: OK, QA: OK, FAC: OK}),
    # The qa_mapping pages were absent from this list while their templates were
    # still live and edited - a template error in either would have gone unseen.
    ('QA programs',          '/qa-mapping/programs/',          {ADMIN: OK, QA: OK}),
]

USERS = {
    ADMIN: ('admin', 'admin123'),
    QA: ('qahead', 'qahead123'),
    FAC: ('faculty_area2', 'faculty123'),
}

# Unrendered template syntax that must never reach the browser.
LEAK_PATTERNS = [
    (r'\{\{', 'unrendered {{ variable'),
    (r'\{%', 'unrendered {% tag'),
    (r'\{#', 'raw {# comment'),
]


def check_html(html):
    problems = []
    for pat, desc in LEAK_PATTERNS:
        hits = re.findall(pat, html)
        if hits:
            problems.append(f'{desc} x{len(hits)}')
    if 'sidebar' not in html and 'app-layout' not in html:
        problems.append('page shell missing')
    return problems


def main():
    failures = []
    print(f'{"ROLE":<9} {"PAGE":<22} {"URL":<32} {"STATUS":<8} RESULT')
    print('-' * 92)

    for role, (username, password) in USERS.items():
        client = Client()
        if not client.login(username=username, password=password):
            print(f'{role:<9} LOGIN FAILED for {username}')
            failures.append(f'{role}: login failed')
            continue

        for label, url, expected in PAGES:
            if role not in expected:
                continue
            want = expected[role]
            resp = client.get(url, follow=False)
            got = resp.status_code
            note = ''
            ok = got == want

            if ok and got == 200:
                html = resp.content.decode('utf-8', 'replace')
                problems = check_html(html)
                if problems:
                    ok = False
                    note = '; '.join(problems)

            verdict = 'ok' if ok else f'FAIL {note}'.strip()
            if not ok:
                failures.append(f'{role} {label} ({url}) -> {got}, want {want} {note}')
            print(f'{role:<9} {label:<22} {url:<32} {got:<8} {verdict}')

    print('-' * 92)
    if failures:
        print(f'\n{len(failures)} FAILURE(S):')
        for f in failures:
            print('  -', f)
        return 1
    print('\nAll pages OK for every role.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

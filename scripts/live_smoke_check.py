"""Live HTTP smoke check against running dev server."""
from __future__ import annotations

import sys
from dataclasses import dataclass

import requests

BASE = 'http://127.0.0.1:8000'

USERS = {
    'admin': ('admin', 'admin123'),
    'qahead': ('qahead', 'qahead123'),
    'faculty': ('faculty_area2', 'faculty123'),
}

PAGES = [
    ('/', None),
    ('/dashboard/', None),
    ('/documents/repository/', None),
    ('/documents/repository/?duplicate=review', 'qa_only'),
    ('/documents/area-submissions/', 'qa_only'),
    ('/documents/clusters/', 'qa_only'),
    ('/documents/upload/', None),
    ('/documents/faculty-upload/', 'faculty_ok'),
    ('/documents/bulk-upload/', None),
    ('/chatbot/', None),
    ('/ai-processing/', 'admin_only'),
    ('/reports/', 'admin_only'),
    ('/accounts/users/', 'admin_only'),
    ('/notifications/mark-all-read/', None),
]


@dataclass
class Result:
    role: str
    path: str
    status: int
    final_url: str
    issue: str = ''


def login(session: requests.Session, username: str, password: str) -> bool:
    r = session.get(f'{BASE}/accounts/login/')
    if r.status_code != 200:
        return False
    csrf = session.cookies.get('csrftoken') or _csrf_from_html(r.text)
    data = {'username': username, 'password': password, 'csrfmiddlewaretoken': csrf}
    r = session.post(f'{BASE}/accounts/login/', data=data, headers={'Referer': f'{BASE}/accounts/login/'})
    return r.status_code in (200, 302) and 'login' not in r.url


def _csrf_from_html(html: str) -> str:
    marker = 'name="csrfmiddlewaretoken" value="'
    i = html.find(marker)
    if i == -1:
        return ''
    start = i + len(marker)
    end = html.find('"', start)
    return html[start:end]


def check_role(role: str, creds: tuple[str, str]) -> list[Result]:
    session = requests.Session()
    if not login(session, creds[0], creds[1]):
        return [Result(role, '/accounts/login/', 0, '', 'LOGIN FAILED')]
    out: list[Result] = []
    for path, gate in PAGES:
        r = session.get(f'{BASE}{path}', allow_redirects=True, timeout=15)
        issue = ''
        if r.status_code >= 500:
            issue = f'SERVER ERROR {r.status_code}'
        elif gate == 'admin_only' and role != 'admin':
            if r.status_code == 200 and 'repository' not in r.url and 'login' not in r.url:
                issue = f'should be denied, got {r.status_code} at {r.url}'
        elif gate == 'qa_only' and role == 'faculty':
            if r.status_code == 200 and 'area-submissions' in r.url or 'clusters' in r.url:
                issue = 'faculty should not access qa-only page'
            if r.status_code == 200 and 'duplicate=review' in path and 'duplicate' in r.text and 'name="duplicate"' in r.text:
                issue = 'faculty sees duplicate filter'
        elif gate == 'faculty_ok' and role == 'faculty':
            if r.status_code == 302 and 'faculty-upload' not in r.url:
                issue = f'faculty upload redirect unexpected: {r.url}'
        elif r.status_code == 403:
            issue = '403 forbidden'
        out.append(Result(role, path, r.status_code, r.url, issue))
    return out


def main() -> int:
    problems: list[Result] = []
    for role, creds in USERS.items():
        for res in check_role(role, creds):
            flag = 'ISSUE' if res.issue else 'OK'
            print(f'[{flag}] {role:8} {res.status:3} {res.path} -> {res.final_url[:80]}')
            if res.issue:
                print(f'         {res.issue}')
                problems.append(res)
    print(f'\nTotal issues: {len(problems)}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())

"""
Exercise the interactive flows the UI cleanup touched, not just page loads.

The page smoke check only issues GETs. This drives the actual features - searching
with a query, filtering, exporting, downloading, opening a document, the chatbot -
and asserts each produces the right kind of response.

Read-only: nothing here creates, edits or deletes a document.

Usage:  python scripts/ui_feature_check.py
"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qa_archiving_system.settings')
os.environ.setdefault('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver')
django.setup()

from django.test import Client  # noqa: E402
from documents.models import Document  # noqa: E402

results = []


def check(label, ok, detail=''):
    results.append((label, ok, detail))
    print(f'  {"ok  " if ok else "FAIL"}  {label:<48} {detail}')


def main():
    c = Client()
    assert c.login(username='admin', password='admin123'), 'admin login failed'
    doc = Document.objects.filter(is_archived=False).first()

    print('\nSEARCH (standalone page removed; search lives in the Repository)')
    r = c.get('/documents/repository/', {'q': 'quality'})
    body = r.content.decode('utf-8', 'replace')
    check('repository search with query returns 200', r.status_code == 200)
    check('search rendered a results region', 'TITLE' in body.upper() or 'result' in body.lower())
    check('removed PK filters are gone from the form', 'Parameter PK' not in body)
    r2 = c.get('/documents/repository/', {'q': 'quality', 'file_type': 'DOCX'})
    check('file_type filter still accepted', r2.status_code == 200)
    # the retired URL must still resolve, forwarding the query rather than 404ing
    r3 = c.get('/search/', {'q': 'quality'})
    check('old /search/ URL redirects, not 404s', r3.status_code == 302, r3.get('Location', ''))
    check('redirect carries the query across', 'q=quality' in r3.get('Location', ''))

    print('\nREPOSITORY (row action styling changed)')
    r = c.get('/documents/repository/')
    body = r.content.decode('utf-8', 'replace')
    check('repository loads', r.status_code == 200)
    check('row action buttons still present', body.count('class="act') >= 3,
          f'{body.count(chr(34)) and body.count("class=" + chr(34) + "act")} buttons')
    for f in [{'area': 'Area II'}, {'year': '2026'}, {'duplicate': 'possible'}]:
        rr = c.get('/documents/repository/', f)
        check(f'filter {list(f)[0]}={list(f.values())[0]}', rr.status_code == 200)

    print('\nDOCUMENT ACTIONS')
    if doc:
        for label, url in [
            ('detail', f'/documents/{doc.pk}/'),
            ('serve', f'/documents/{doc.pk}/serve/'),
            ('download', f'/documents/{doc.pk}/download/'),
            ('edit form', f'/documents/{doc.pk}/edit/'),
        ]:
            rr = c.get(url)
            ok = rr.status_code in (200, 302)
            check(f'{label} (doc #{doc.pk})', ok, f'HTTP {rr.status_code}')

        # Preview is a PDF rendering, so it only exists for types that can be
        # turned into one. This used to run against whatever document was newest
        # and failed the moment someone uploaded a spreadsheet -- a 404 the view
        # raises on purpose, not a fault. Check a document that can actually
        # have a preview.
        previewable = Document.objects.filter(file_type__in=['pdf', 'docx']).first()
        if previewable:
            rr = c.get(f'/documents/{previewable.pk}/preview/')
            check(f'preview (doc #{previewable.pk}, {previewable.file_type})',
                  rr.status_code in (200, 302), f'HTTP {rr.status_code}')
    else:
        check('a document exists to test against', False, 'no documents in DB')

    print('\nEXPORTS (Export Excel restyled on two pages)')
    r = c.get('/dashboard/', {'export': 'excel'})
    ctype = r.get('Content-Type', '')
    check('dashboard Export Excel returns a file', r.status_code == 200 and 'sheet' in ctype,
          ctype[:46])
    r = c.get('/reports/export/excel/', {'type': 'inventory'})
    ctype = r.get('Content-Type', '')
    check('reports Export Excel returns a file', r.status_code == 200 and 'sheet' in ctype,
          ctype[:46])

    print('\nUPLOAD FORM (placeholders changed on 6 selects)')
    r = c.get('/documents/upload/')
    body = r.content.decode('utf-8', 'replace')
    check('upload form loads', r.status_code == 200)
    check('Django default "---------" is gone', '---------' not in body)
    check('new placeholder present', 'Select area' in body)
    # form still validates: submitting empty must re-render with errors, not 500
    r = c.post('/documents/upload/', {})
    check('empty submit re-renders with errors (no 500)', r.status_code == 200)
    check('required-field errors shown', 'required' in r.content.decode('utf-8', 'replace').lower())

    print('\nSETTINGS (engine status made real)')
    r = c.get('/accounts/settings/')
    body = r.content.decode('utf-8', 'replace')
    check('settings loads', r.status_code == 200)
    # count only rendered badges, not the three CSS rule definitions above them
    rendered_badges = body.count('<div class="status-badge')
    check('engine rows rendered from context', rendered_badges == 5,
          f'{rendered_badges} badges')
    check('upload limit reads from settings', ' MB' in body)

    print('\nOTHER PAGES TOUCHED')
    for label, url in [('reports inventory', '/reports/?type=inventory'),
                       ('reports cluster', '/reports/?type=cluster'),
                       ('reports activity', '/reports/?type=activity'),
                       ('clusters', '/documents/clusters/'),
                       ('area submissions', '/documents/area-submissions/'),
                       ('ai processing', '/ai-processing/'),
                       ('audit log', '/accounts/audit-log/'),
                       ('user management', '/accounts/users/')]:
        rr = c.get(url)
        check(label, rr.status_code == 200, f'HTTP {rr.status_code}')

    print('\nCHATBOT')
    r = c.post('/chatbot/api/', {'message': 'where is upload'},
               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    check('chatbot answers', r.status_code in (200, 302), f'HTTP {r.status_code}')

    print('\nSIDEBAR')
    sb = c.get('/dashboard/').content.decode('utf-8', 'replace')
    check('Smart Search entry removed from sidebar', 'data-tooltip="Smart Search"' not in sb)
    check('QA Checklist entry removed from sidebar', 'qa-mapping/checklist' not in sb)

    print('\nTABLE HEADER / ROW ACTIONS')
    repo = c.get('/documents/repository/').content.decode('utf-8', 'replace')
    check('action icons carry a per-action class',
          all(f'act {name}' in repo for name in ('view', 'info', 'download', 'edit', 'delete')))
    css = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'static', 'css', 'style.css'), encoding='utf-8').read()
    check('sticky header keeps its containing block',
          '.repo-scroll-panel > .table-responsive{overflow:visible}' in css)

    failed = [r for r in results if not r[1]]
    print('\n' + '-' * 78)
    print(f'{len(results) - len(failed)} / {len(results)} checks passed')
    if failed:
        print('\nFAILURES:')
        for label, _, detail in failed:
            print(f'  - {label} {detail}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

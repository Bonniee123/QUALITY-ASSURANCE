"""Extended live checks: API endpoints and content assertions."""
import requests

BASE = 'http://127.0.0.1:8000'


def login(username, password):
    s = requests.Session()
    s.get(f'{BASE}/accounts/login/')
    csrf = s.cookies.get('csrftoken')
    s.post(
        f'{BASE}/accounts/login/',
        data={'username': username, 'password': password, 'csrfmiddlewaretoken': csrf},
        headers={'Referer': f'{BASE}/accounts/login/'},
    )
    return s


issues = []

# Chatbot
s = login('qahead', 'qahead123')
csrf = s.cookies.get('csrftoken')
r = s.post(
    f'{BASE}/chatbot/api/',
    data={'message': 'How do I review duplicates?'},
    headers={'X-CSRFToken': csrf, 'Referer': f'{BASE}/chatbot/'},
)
print('chatbot', r.status_code, r.json().get('response', r.text)[:120])
if r.status_code != 200:
    issues.append('Chatbot API failed for QA Head')

# Search
r = s.get(f'{BASE}/documents/repository/?q=quality')
print('search', r.status_code, 'results' if 'result' in r.text.lower() or 'document' in r.text.lower() else 'empty?')
if r.status_code != 200:
    issues.append('Search failed')

# AJAX cluster partial
r = s.get(f'{BASE}/documents/clusters/?cluster=3', headers={'X-Requested-With': 'XMLHttpRequest'})
print('cluster ajax', r.status_code, 'cluster-detail' in r.text)
if 'cluster-detail' not in r.text:
    issues.append('Cluster AJAX partial missing detail')

# AJAX area partial
r = s.get(f'{BASE}/documents/area-submissions/?area=Area%20II', headers={'X-Requested-With': 'XMLHttpRequest'})
print('area ajax', r.status_code, 'area-detail' in r.text)
if 'area-detail' not in r.text:
    issues.append('Area submission AJAX partial missing detail')

# Duplicate dismiss endpoint exists (GET should redirect, not 500)
r = s.get(f'{BASE}/documents/147/duplicate-dismiss/')
print('dismiss get', r.status_code, r.url)
if r.status_code >= 500:
    issues.append('duplicate-dismiss throws 500 on GET')

# Faculty scoped repository count sanity
f = login('faculty_area2', 'faculty123')
r_all = f.get(f'{BASE}/documents/repository/')
r_dup = f.get(f'{BASE}/documents/repository/?duplicate=review')
rows_all = r_all.text.count('doc-row')
rows_dup = r_dup.text.count('doc-row')
print('faculty rows all/dup', rows_all, rows_dup)
if rows_dup != rows_all and 'duplicate' not in r_dup.text:
    issues.append('Faculty duplicate URL param still filters results server-side')

# Admin-only pages content
a = login('admin', 'admin123')
r = a.get(f'{BASE}/ai-processing/')
print('admin ai', r.status_code, 'AI Processing' in r.text)
r = a.get(f'{BASE}/reports/')
print('admin reports', r.status_code, 'Reports' in r.text or 'report' in r.text.lower())

print('\nIssues found:', len(issues))
for i in issues:
    print(' -', i)

import requests

s = requests.Session()
s.get('http://127.0.0.1:8000/accounts/login/')
csrf = s.cookies.get('csrftoken')
s.post(
    'http://127.0.0.1:8000/accounts/login/',
    data={'username': 'faculty_area2', 'password': 'faculty123', 'csrfmiddlewaretoken': csrf},
    headers={'Referer': 'http://127.0.0.1:8000/accounts/login/'},
)
r = s.get('http://127.0.0.1:8000/documents/repository/?duplicate=review')
r2 = s.get('http://127.0.0.1:8000/documents/repository/')
print('filter_ui_visible', 'name="duplicate"' in r.text)
print('duplicate_column', 'Duplicate</th>' in r.text)
print('rows_with_dup_filter', r.text.count('doc-row'))
print('rows_normal', r2.text.count('doc-row'))

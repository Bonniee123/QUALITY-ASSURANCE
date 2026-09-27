"""Dev-only smoke crawl: GET every no-argument URL as an admin and report status."""
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

User = get_user_model()


def collect(resolver, prefix=''):
    urls = []
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            urls += collect(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            pat = str(p.pattern)
            full = prefix + pat
            # Skip patterns that need arguments or are non-GET endpoints.
            if '<' in full or '(?P' in full:
                continue
            # Skip endpoints that would destroy our own session or are not app pages.
            if 'logout' in full or full.startswith('admin/'):
                continue
            urls.append('/' + full.lstrip('/'))
    return urls


admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(username='admin').first()
c = Client()
if admin:
    c.force_login(admin)
    print(f'Logged in as: {admin.username}')
else:
    print('No admin user found; crawling anonymously.')

seen = sorted(set(collect(get_resolver())))
ok, redir, bad = [], [], []
for url in seen:
    try:
        r = c.get(url, HTTP_HOST='127.0.0.1')
        code = r.status_code
    except Exception as e:  # noqa: BLE001
        bad.append((url, f'EXC: {type(e).__name__}: {e}'))
        continue
    if code in (200, 204):
        ok.append((url, code))
    elif code in (301, 302, 303, 307, 308):
        redir.append((url, code, r.headers.get('Location', '')))
    else:
        bad.append((url, code))

print(f'\n=== OK ({len(ok)}) ===')
for u, code in ok:
    print(f'  {code}  {u}')
print(f'\n=== REDIRECT ({len(redir)}) ===')
for u, code, loc in redir:
    print(f'  {code}  {u}  ->  {loc}')
print(f'\n=== PROBLEM ({len(bad)}) ===')
for u, info in bad:
    print(f'  {info}  {u}')
print(f'\nTOTAL: {len(seen)}  | OK: {len(ok)}  REDIRECT: {len(redir)}  PROBLEM: {len(bad)}')

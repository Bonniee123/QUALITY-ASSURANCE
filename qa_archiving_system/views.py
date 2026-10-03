"""
The pages that keep working when the connection does not: the offline page,
the service worker that serves it, and the health check that says the
connection is back.

None of them needs a session or the database, so they answer even when the
person has been signed out or the database is down, and they are reachable
without signing in.
"""
import os

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
def offline(request):
    return HttpResponse(render_to_string('offline.html'))


@require_GET
@never_cache
def healthz(request):
    """'Is the server reachable?' -- an empty 204, nothing to cache or leak."""
    return HttpResponse(status=204)


@require_GET
@never_cache
def service_worker(request):
    # Served from the site root, not /static/, so its scope covers every page.
    # The version follows the offline page's templates: change one and the
    # browser installs the worker again and caches the new page.
    version = _offline_page_version()
    response = HttpResponse(
        render_to_string('status/sw.js', {'version': version}),
        content_type='application/javascript; charset=utf-8',
    )
    response['Service-Worker-Allowed'] = '/'
    return response


_OFFLINE_TEMPLATES = ('offline.html', 'status/base.html', 'status/_offline_card.html', 'status/_scene.html',
                      'status/_styles.css', 'status/_reconnect.js', 'status/_icon.html', 'status/sw.js')


def _offline_page_version() -> str:
    stamps = []
    for name in _OFFLINE_TEMPLATES:
        try:
            stamps.append(int(os.path.getmtime(settings.BASE_DIR / 'templates' / name)))
        except OSError:
            continue
    return str(max(stamps)) if stamps else '1'

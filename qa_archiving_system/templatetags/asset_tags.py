"""
Cache-busting for the project's own static files.

Django's development static server sends ``Last-Modified`` but no ``ETag`` and no
``Cache-Control``. With no explicit freshness directive a browser is free to
heuristically cache the file and skip revalidating it, which is exactly what
happened after a stylesheet fix: the corrected rule sat on disk while the browser
kept serving the old declaration, and the bug looked unfixed.

``{% static_v 'css/style.css' %}`` appends the file's modification time as a query
string, so editing the file changes its URL and the browser is obliged to fetch it.
Unchanged files keep a stable URL and stay cached.

In production ``ManifestStaticFilesStorage`` would hash the name instead; this tag
defers to whatever ``static`` returns and only adds the stamp when the source file
can be found on disk, so it is harmless either way.
"""
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

# Where each file lives is looked up once: searching the finders walks the
# static directories. Its modification time is read on every use -- one stat
# call -- because the stamp is the whole point. It used to be cached for the
# life of the process, so files replaced while the server was running (copied
# in from an updated checkout, say) kept their old ?v= stamp, the browser kept
# serving its cached copy under that address, and the update looked missing
# until the server was restarted.
_path_cache: dict[str, str] = {}


def _resolve(path: str) -> str:
    if path not in _path_cache:
        absolute = finders.find(path)
        if isinstance(absolute, (list, tuple)):
            absolute = absolute[0] if absolute else ''
        _path_cache[path] = absolute or ''
    return _path_cache[path]


def _stamp(path: str) -> str:
    """The file's mtime as a short string, or '' if it cannot be located."""
    try:
        absolute = _resolve(path)
        if not absolute:
            _path_cache.pop(path, None)   # it may appear later; look again next time
            return ''
        return str(int(os.path.getmtime(absolute)))
    except (OSError, ValueError):  # missing file, odd storage
        _path_cache.pop(path, None)
        return ''


@register.simple_tag
def static_v(path: str) -> str:
    """Like ``{% static %}``, but versioned by the file's modification time."""
    url = static(path)
    stamp = _stamp(path)
    if not stamp:
        return url
    separator = '&' if '?' in url else '?'
    return f'{url}{separator}v={stamp}'

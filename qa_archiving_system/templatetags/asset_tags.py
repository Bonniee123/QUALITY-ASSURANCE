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

# Resolving a path through the finders touches the filesystem, so the answer is
# kept for the life of the process. runserver restarts on a code change, and a
# static-file edit changes the mtime, not the resolved path.
_stamp_cache: dict[str, str] = {}


def _stamp(path: str) -> str:
    """The file's mtime as a short string, or '' if it cannot be located."""
    if path in _stamp_cache:
        return _stamp_cache[path]
    stamp = ''
    try:
        absolute = finders.find(path)
        if absolute:
            if isinstance(absolute, (list, tuple)):
                absolute = absolute[0]
            stamp = str(int(os.path.getmtime(absolute)))
    except (OSError, ValueError):  # pragma: no cover - missing file, odd storage
        stamp = ''
    _stamp_cache[path] = stamp
    return stamp


@register.simple_tag
def static_v(path: str) -> str:
    """Like ``{% static %}``, but versioned by the file's modification time."""
    url = static(path)
    stamp = _stamp(path)
    if not stamp:
        return url
    separator = '&' if '?' in url else '?'
    return f'{url}{separator}v={stamp}'

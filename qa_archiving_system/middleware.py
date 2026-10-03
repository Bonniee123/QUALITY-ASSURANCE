"""Production security middleware."""
import posixpath

from django.conf import settings
from django.http import HttpResponseForbidden


# Sources the app legitimately loads from (CDNs in base.html).
_CSP_DIRECTIVES = {
    'default-src': ["'self'"],
    # 'unsafe-inline' is required because templates use inline <script> blocks.
    # The real protection here is restricting external origins + blocking
    # object/embed and locking base-uri/form-action. Upgrading to nonce-based
    # CSP (removing 'unsafe-inline') is the stricter future step.
    'script-src': ["'self'", 'https://cdn.jsdelivr.net', "'unsafe-inline'"],
    'style-src': [
        "'self'", 'https://cdn.jsdelivr.net',
        'https://fonts.googleapis.com', "'unsafe-inline'",
    ],
    'font-src': ["'self'", 'https://fonts.gstatic.com', 'https://cdn.jsdelivr.net', 'data:'],
    'img-src': ["'self'", 'data:', 'blob:'],
    'connect-src': ["'self'"],
    'frame-ancestors': ["'self'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
    # The in-browser document viewer renders the PDF preview through an
    # <embed> backed by a blob: URL, so object/frame sources must allow
    # 'self' and blob: (external plugins/sites stay blocked).
    'object-src': ["'self'", 'blob:'],
    'frame-src': ["'self'", 'blob:'],
}


def _build_csp() -> str:
    return '; '.join(f"{name} {' '.join(values)}" for name, values in _CSP_DIRECTIVES.items())


class SecurityHeadersMiddleware:
    """
    Adds defense-in-depth response headers that are not covered by Django's
    built-in SECURE_* settings:

    - Content-Security-Policy: the strongest browser-level guard against XSS;
      tells the browser exactly which script/style/font/image origins may load.
    - Permissions-Policy: disables powerful browser features the app never uses
      (camera, geolocation), shrinking the attack surface. The microphone is
      allowed for this site's own pages only -- voice messages need it -- and
      stays off for anything framed from elsewhere.
    - X-Content-Type-Options: prevents MIME-type sniffing.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = _build_csp()

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', self.csp)
        response.setdefault('X-Content-Type-Options', 'nosniff')
        response.setdefault(
            'Permissions-Policy',
            'camera=(), microphone=(self), geolocation=(), interest-cohort=()',
        )
        return response


def _normalised_path(path: str) -> str:
    """
    The path a file server would actually open for this URL.

    "profile_pics/../uploaded_documents/x.pdf" names a document, not a photo,
    and on Windows a backslash separates folders as well.
    """
    return posixpath.normpath('/' + path.replace('\\', '/').lstrip('/'))


class BlockPublicMediaMiddleware:
    """
    Block direct HTTP access to /media/, whatever DEBUG is set to.

    Uploaded documents must be served through authenticated views
    (document_serve, document_download, document_preview), which apply the
    role and area checks. This used to apply only when DEBUG=False, but DEBUG
    is on by default and the development media route then handed any file to
    anyone who knew its path, signed in or not.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        prefix = (settings.MEDIA_URL or '/media/').rstrip('/')
        self.media_prefix = f'{prefix}/'
        # Non-sensitive assets (profile pictures) may be served directly.
        self.allowed_prefix = f'{prefix}/profile_pics/'

    def __call__(self, request):
        normalised = _normalised_path(request.path)
        if (
            (request.path.startswith(self.media_prefix) or normalised.startswith(self.media_prefix))
            and not normalised.startswith(self.allowed_prefix)
        ):
            return HttpResponseForbidden(
                'Direct access to uploaded files is not permitted. '
                'Sign in and open the document from the repository.'
            )
        return self.get_response(request)

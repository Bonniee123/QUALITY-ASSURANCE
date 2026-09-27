"""
The app's own error pages while DEBUG is on.

With DEBUG on -- the default on this laptop -- Django answers a missing page or
a crash with its technical page: the error code, the URL patterns, the
traceback and the settings. The friendly pages in templates/ (404.html,
500.html, 400.html) were only used with DEBUG off. This middleware shows them
in both modes.

Nothing is lost for the developer: Django still logs every error, traceback
included, to the runserver console (the django.request logger). To see
Django's technical pages in the browser again, set SHOW_DEBUG_ERROR_PAGES=True.

403.html and 403_csrf.html need nothing from here: Django uses them whatever
DEBUG is set to.
"""
from django.conf import settings
from django.core.exceptions import BadRequest, SuspiciousOperation
from django.http import Http404, HttpResponseNotFound
from django.template import loader
from django.views.debug import ExceptionReporter


def _render(template_name: str, fallback: str) -> str:
    """The template on its own -- no request, no context processors -- so it renders even when those are broken."""
    try:
        return loader.render_to_string(template_name)
    except Exception:
        return f'<!DOCTYPE html><html lang="en"><head><title>{fallback}</title></head><body><p>{fallback}</p></body></html>'


def not_found_response():
    return HttpResponseNotFound(_render('404.html', 'Page not found'))


class FriendlyExceptionReporter(ExceptionReporter):
    """Stands in for Django's technical error page; the status code stays what Django chose."""

    def _is_bad_request(self):
        return self.exc_type is not None and issubclass(self.exc_type, (SuspiciousOperation, BadRequest))

    def get_traceback_html(self):
        if self._is_bad_request():
            return _render('400.html', 'The request could not be processed')
        return _render('500.html', 'Something went wrong')

    def get_traceback_text(self):
        # Sent when the caller asked for something other than HTML (the upload page's XHR, for one).
        if self._is_bad_request():
            return 'The request could not be processed. Please go back and try again.'
        return 'Something went wrong. Please try again in a moment.'


def _active() -> bool:
    return settings.DEBUG and not getattr(settings, 'SHOW_DEBUG_ERROR_PAGES', False)


class FriendlyErrorPagesMiddleware:
    """Swap Django's DEBUG-mode technical pages for the app's own (see the module docstring)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _active():
            return self.get_response(request)
        # Django builds its technical 500 / 400 page with the request's reporter class.
        request.exception_reporter_class = FriendlyExceptionReporter
        response = self.get_response(request)
        # An address that matches no route never reaches a view, so process_exception
        # does not see it; Django's technical 404 arrives here instead.
        if response.status_code == 404 and getattr(request, 'resolver_match', None) is None:
            return not_found_response()
        return response

    def process_exception(self, request, exception):
        if _active() and isinstance(exception, Http404):
            return not_found_response()
        return None

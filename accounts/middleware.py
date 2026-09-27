"""Log out authenticated users after a period of inactivity."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

# Sent by the page's own automatic refreshes (message badges, upload and job
# progress, the Messages sync) once nobody has touched the page for a minute.
PASSIVE_HEADER = 'X-QA-Passive'


def is_passive_request(request) -> bool:
    """
    True for an automatic request made while nobody is at the page.

    Such a request is not the person doing anything: it neither keeps their
    session alive nor, in Messages, counts as them having read what arrived.
    """
    return request.headers.get(PASSIVE_HEADER) == '1'


def _wants_json(request) -> bool:
    return (
        is_passive_request(request)
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    )


class SessionIdleTimeoutMiddleware:
    """
    End the session when the user has been inactive longer than SESSION_IDLE_TIMEOUT.
    Must be placed after AuthenticationMiddleware.

    "Inactive" means the person did nothing -- not that the page went quiet.
    Every open page refreshes its badges every few seconds, and those refreshes
    used to count as activity, so the clock was reset every five seconds for as
    long as a tab stayed open: a screen left signed in on a shared office PC
    stayed signed in indefinitely, showing whatever it was showing. Refreshes
    now say when nobody is at the page, and only real use resets the clock.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = int(getattr(settings, 'SESSION_IDLE_TIMEOUT', 0))

    def __call__(self, request):
        if self.timeout > 0 and request.user.is_authenticated:
            now_ts = timezone.now().timestamp()
            last_ts = request.session.get('_auth_last_activity')
            if last_ts is not None and (now_ts - float(last_ts)) > self.timeout:
                logout(request)
                messages.warning(
                    request,
                    'Your session expired due to inactivity. Please sign in again.',
                )
                if _wants_json(request):
                    # A background request cannot be redirected in any way the
                    # page would notice -- fetch follows the redirect and gets
                    # the sign-in page as "data", and the screen stays as it
                    # was. A plain 401 lets the page take itself to sign-in.
                    response = JsonResponse({'session_expired': True}, status=401)
                    response['X-QA-Login'] = reverse('accounts:login')
                    return response
                return redirect('accounts:login')
            if not is_passive_request(request):
                request.session['_auth_last_activity'] = now_ts

        return self.get_response(request)

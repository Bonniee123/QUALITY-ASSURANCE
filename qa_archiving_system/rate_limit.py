"""
Request limits for the heavy actions: QA Assistant messages, upload batches and
ZIP downloads.

Counters live in Django's cache, as the login lockout's do
(accounts.auth_security). Each is kept per account *and* per device IP, so
people sharing one account from different computers -- a test session, say --
do not use up each other's allowance.

A window opens with the first request and lasts a fixed time: later requests
do not extend it, so steady use below the limit never accumulates into a block.
"""
from __future__ import annotations

import math
import time

from django.conf import settings
from django.core.cache import cache

from accounts.auth_security import get_client_ip
from documents.audit import log_activity

# scope -> (limit setting, window setting, default limit, default window, what the user was doing)
_SCOPES = {
    'chatbot': ('CHATBOT_RATE_LIMIT', 'CHATBOT_RATE_LIMIT_WINDOW', 20, 60, 'QA Assistant messages'),
    'upload': ('UPLOAD_RATE_LIMIT', 'UPLOAD_RATE_LIMIT_WINDOW', 15, 600, 'upload batches'),
    'zip': ('ZIP_RATE_LIMIT', 'ZIP_RATE_LIMIT_WINDOW', 10, 600, 'ZIP downloads'),
}


def _key(request, scope: str) -> str:
    user_id = getattr(request.user, 'pk', None) or 'anon'
    return f'qa_rate:{scope}:{user_id}:{get_client_ip(request)}'


def _config(scope: str):
    limit_name, window_name, default_limit, default_window, label = _SCOPES[scope]
    limit = int(getattr(settings, limit_name, default_limit))
    window = int(getattr(settings, window_name, default_window))
    return limit, window, label


def allow(request, scope: str) -> bool:
    """
    Count this request against ``scope`` and say whether it may go ahead.

    A refused request is not counted, so access returns as soon as the window
    ends. The first refusal in a window is written to the audit log under the
    existing "Access denied" action -- only the first, or a script hammering an
    endpoint would flood the log.
    """
    limit, window, label = _config(scope)
    if limit <= 0 or window <= 0:
        return True

    key = _key(request, scope)
    now = time.time()
    started, count = cache.get(key) or (now, 0)
    if now - started >= window:
        started, count = now, 0
    remaining = max(1, math.ceil(started + window - now))

    if count >= limit:
        if cache.add(f'{key}:logged', True, timeout=remaining):
            log_activity(request, 'permission_denied', f'Too many {label}: limit is {describe_limit(scope)}.')
        return False

    cache.set(key, (started, count + 1), timeout=remaining)
    return True


def describe_limit(scope: str) -> str:
    """The configured limit of ``scope`` for a message: '20 per minute', '15 per 10 minutes'."""
    limit, window, _label = _config(scope)
    if window % 60 == 0:
        minutes = window // 60
        return f'{limit} per minute' if minutes == 1 else f'{limit} per {minutes} minutes'
    return f'{limit} per {window} seconds'

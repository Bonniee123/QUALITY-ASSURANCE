"""Login rate limiting, session helpers, and authentication audit logging."""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from documents.audit import log_activity


def get_client_ip(request) -> str:
    """
    Best-effort client IP.

    X-Forwarded-For is read only when TRUST_X_FORWARDED_FOR is on, i.e. behind
    a proxy that sets it. Anyone can send that header, and trusting it
    unconditionally let a client pick a fresh "IP" for every failed login.

    Even then the *last* entry is used: nginx's $proxy_add_x_forwarded_for
    (scripts/nginx_qa_archive.conf.example) appends the address it saw to
    whatever the client sent, so only the last one is the proxy's own word.
    """
    if getattr(settings, 'TRUST_X_FORWARDED_FOR', False):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        hops = [hop.strip() for hop in forwarded.split(',') if hop.strip()]
        if hops:
            return hops[-1]
    return request.META.get('REMOTE_ADDR') or 'unknown'


def _attempt_key(kind: str, identifier: str) -> str:
    return f'qa_login_attempts:{kind}:{identifier}'


def _lock_key(kind: str, identifier: str) -> str:
    return f'qa_login_locked:{kind}:{identifier}'


def _max_attempts() -> int:
    return int(getattr(settings, 'LOGIN_RATE_LIMIT_ATTEMPTS', 5))


def _attempt_window() -> int:
    return int(getattr(settings, 'LOGIN_RATE_LIMIT_WINDOW', 900))


def _lockout_seconds() -> int:
    return int(getattr(settings, 'LOGIN_RATE_LIMIT_LOCKOUT', 900))


def is_login_locked(request, username: str) -> bool:
    """True when IP or username is temporarily locked after too many failures."""
    ip = get_client_ip(request)
    username_key = (username or '').strip().lower()
    keys = [_lock_key('ip', ip)]
    if username_key:
        keys.append(_lock_key('user', username_key))
    return any(cache.get(key) for key in keys)


def lockout_message() -> str:
    minutes = max(1, _lockout_seconds() // 60)
    return (
        f'Too many failed login attempts. Please wait {minutes} minute(s) '
        'and try again, or contact the administrator.'
    )


def record_failed_login(request, username: str) -> int:
    """
    Increment failure counters for IP and username.
    Returns remaining attempts before lockout (minimum across keys), or 0 if locked.
    """
    ip = get_client_ip(request)
    username_key = (username or '').strip().lower()
    window = _attempt_window()
    lockout = _lockout_seconds()
    max_attempts = _max_attempts()
    remaining = max_attempts

    targets = [('ip', ip)]
    if username_key:
        targets.append(('user', username_key))

    for kind, ident in targets:
        attempt_key = _attempt_key(kind, ident)
        attempts = int(cache.get(attempt_key, 0)) + 1
        cache.set(attempt_key, attempts, timeout=window)
        if attempts >= max_attempts:
            cache.set(_lock_key(kind, ident), True, timeout=lockout)
            remaining = 0
        else:
            remaining = min(remaining, max_attempts - attempts)

    log_failed_login(request, username)
    return remaining


def clear_login_attempts(request, username: str) -> None:
    """Reset counters after a successful login."""
    ip = get_client_ip(request)
    username_key = (username or '').strip().lower()
    for kind, ident in [('ip', ip), ('user', username_key)]:
        if not ident:
            continue
        cache.delete(_attempt_key(kind, ident))
        cache.delete(_lock_key(kind, ident))


def log_failed_login(request, username: str) -> None:
    """Write failed login attempts to the activity log (user may be null)."""
    label = (username or '').strip() or '(blank username)'
    log_activity(request, 'login_failed', f'Failed login for username "{label}".', user=None)


def log_successful_login(user, request) -> None:
    log_activity(request, 'login', f'{user.username} logged in.', user=user)

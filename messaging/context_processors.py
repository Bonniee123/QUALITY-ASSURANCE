"""Sidebar badge for unread direct messages."""
from .models import unread_total_for


def messaging_context(request):
    """
    Unread total for the signed-in user.

    Wrapped defensively: a template context processor runs on every page, so a
    failure here would take down the whole site rather than one badge.
    """
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return {}
    try:
        return {'unread_messages': unread_total_for(user)}
    except Exception:  # pragma: no cover - a badge must never break a page
        return {'unread_messages': 0}

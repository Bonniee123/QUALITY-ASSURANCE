"""Sidebar badge for unread direct messages, and the conversation composer's limits."""
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
        unread = unread_total_for(user)
    except Exception:  # pragma: no cover - a badge must never break a page
        unread = 0
    from django.conf import settings

    from accounts.avatars import avatar_url, initials

    from .attachments import FILE_TYPES, IMAGE_TYPES
    return {
        'unread_messages': unread,
        # What the conversation composer may attach, so it can say at once
        # which file cannot be sent; the server checks again.
        'chat_config': {
            'max_mb': int(getattr(settings, 'MESSAGE_ATTACHMENT_MAX_MB', 15)),
            'max_files': int(getattr(settings, 'MESSAGE_ATTACHMENTS_PER_MESSAGE', 10)),
            'accept': ','.join(sorted(set(IMAGE_TYPES) | set(FILE_TYPES))),
            'me_avatar': avatar_url(user),
            'me_initials': initials(user),
        },
    }

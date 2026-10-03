"""Helpers for creating notifications. Safe to call from anywhere; failures are swallowed."""
import logging
from typing import Iterable, Optional

from django.contrib.auth.models import User

from .models import Notification

logger = logging.getLogger(__name__)


def notify(user: User, message: str, *, category: str = 'system', link: str = '',
           dedupe_key: str = '') -> Optional[Notification]:
    """
    Create a single notification. Returns the instance, or None on failure or
    when this person already has the notification for `dedupe_key`.
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return None
    try:
        if dedupe_key and Notification.objects.filter(user=user, dedupe_key=dedupe_key).exists():
            return None
        return Notification.objects.create(
            user=user,
            message=message[:400],
            category=category,
            link=link[:400] if link else '',
            dedupe_key=dedupe_key[:100],
        )
    except Exception as e:
        logger.error("notify() failed for %s: %s", getattr(user, 'username', '?'), e)
        return None


def notify_qa_staff(message: str, *, category: str = 'system', link: str = '',
                    dedupe_key: str = '', exclude=None) -> int:
    """
    Notify every active admin and QA staff user. Returns the number sent.

    `exclude` is the person whose action this is about: nobody is notified of
    their own upload or deletion.
    """
    try:
        users = User.objects.filter(
            is_active=True,
            profile__role__in=('admin', 'qa_staff'),
            profile__status='active',
        ).distinct()
    except Exception as e:
        logger.error("notify_qa_staff() lookup failed: %s", e)
        return 0
    count = 0
    for u in users:
        if exclude is not None and u.pk == exclude.pk:
            continue
        if notify(u, message, category=category, link=link, dedupe_key=dedupe_key):
            count += 1
    return count


def notify_users(users: Iterable[User], message: str, *, category: str = 'system', link: str = '') -> int:
    """Notify a specific iterable of users."""
    count = 0
    for u in users:
        if u and notify(u, message, category=category, link=link):
            count += 1
    return count

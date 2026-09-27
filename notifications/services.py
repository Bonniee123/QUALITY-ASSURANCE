"""Helpers for creating notifications. Safe to call from anywhere; failures are swallowed."""
import logging
from typing import Iterable, Optional

from django.contrib.auth.models import User

from .models import Notification

logger = logging.getLogger(__name__)


def notify(user: User, message: str, *, category: str = 'system', link: str = '') -> Optional[Notification]:
    """Create a single notification. Returns the instance or None on failure."""
    if not user or not getattr(user, 'is_authenticated', True):
        return None
    try:
        return Notification.objects.create(
            user=user,
            message=message[:400],
            category=category,
            link=link[:400] if link else '',
        )
    except Exception as e:
        logger.error("notify() failed for %s: %s", getattr(user, 'username', '?'), e)
        return None


def notify_qa_staff(message: str, *, category: str = 'system', link: str = '') -> int:
    """Notify every active admin and QA staff user. Returns the number sent."""
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
        if notify(u, message, category=category, link=link):
            count += 1
    return count


def notify_users(users: Iterable[User], message: str, *, category: str = 'system', link: str = '') -> int:
    """Notify a specific iterable of users."""
    count = 0
    for u in users:
        if u and notify(u, message, category=category, link=link):
            count += 1
    return count

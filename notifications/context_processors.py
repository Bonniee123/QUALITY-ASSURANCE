"""Expose recent notifications + unread count to every template."""
from .models import Notification


def notifications_context(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'notifications_unread_count': 0, 'recent_notifications': []}
    qs = Notification.objects.filter(user=request.user)
    unread = qs.filter(is_read=False).count()
    recent = list(qs[:8])
    return {
        'notifications_unread_count': unread,
        'recent_notifications': recent,
    }

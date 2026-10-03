"""
Who is online, for the User Management Status column.

A signed-in page asks the server for its badges every few seconds, so any
account with the system open makes a request well inside ONLINE_WINDOW. The
time of that request is stored at most every WRITE_EVERY seconds per session,
so presence costs one small UPDATE per user per half-minute, not one per poll.
Signing out -- by the button or by the idle timeout -- is recorded too, so the
account shows Offline at once instead of lingering until the window closes.
"""
from datetime import timedelta

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from django.utils import timezone
from django.utils.timesince import timesince

ONLINE_WINDOW = timedelta(minutes=3)
WRITE_EVERY = 30  # seconds
SESSION_KEY = '_presence_written'


def record(request) -> None:
    """Note that this signed-in user has the system open."""
    now = timezone.now()
    last = request.session.get(SESSION_KEY)
    if last is not None and now.timestamp() - float(last) < WRITE_EVERY:
        return
    from .models import UserProfile
    UserProfile.objects.filter(user_id=request.user.pk).update(last_seen=now)
    request.session[SESSION_KEY] = now.timestamp()


@receiver(user_logged_out)
def _record_sign_out(sender, request, user, **kwargs):
    if user is None:
        return
    from .models import UserProfile
    UserProfile.objects.filter(user_id=user.pk).update(last_logout=timezone.now())


def presence(user, now=None) -> dict:
    """{'state': 'online' | 'offline' | 'never' | 'inactive', 'label': ...} for one account."""
    now = now or timezone.now()
    profile = getattr(user, 'profile', None)
    if not user.is_active or (profile is not None and profile.status != 'active'):
        return {'state': 'inactive', 'label': 'Inactive'}
    # Accounts that signed in before presence was recorded still have Django's last_login.
    seen = getattr(profile, 'last_seen', None) or user.last_login
    if seen is None:
        return {'state': 'never', 'label': 'Never signed in'}
    signed_out = getattr(profile, 'last_logout', None)
    if now - seen <= ONLINE_WINDOW and (signed_out is None or signed_out < seen):
        return {'state': 'online', 'label': 'Online'}
    last = max(seen, signed_out) if signed_out else seen
    if now - last < timedelta(minutes=1):
        return {'state': 'offline', 'label': 'Last seen just now'}
    return {'state': 'offline', 'label': f'Last seen {timesince(last, now).split(",")[0]} ago'}

"""
Template access to an account's photo.

Templates cannot call ``accounts.avatars`` directly, and ``{{ u.profile.avatar_url }}``
silently yields nothing for an account with no profile row -- which reads the
same as "no photo" and hides the difference. These filters go through the one
helper module instead, so a template and a JSON endpoint answer alike.
"""
from django import template

from accounts.avatars import avatar_url, initials

register = template.Library()


@register.filter(name='avatar_url')
def avatar_url_filter(user) -> str:
    """The account's photo URL, or '' when it has none."""
    return avatar_url(user)


@register.filter(name='avatar_initials')
def avatar_initials_filter(user) -> str:
    """Fallback initials for an account with no photo."""
    return initials(user)

"""
One place that answers "what does this account look like?".

Every surface that shows a person -- the navbar, a user list, a message bubble,
an uploader credit -- resolves the picture through here, from the account that
owns it. Nothing derives a picture from a role, a page, or which side of a
conversation is being read, so the photo always follows the account.

Both helpers accept anything user-shaped, including ``None`` and an account with
no profile row, because a deleted uploader and a half-migrated account both
reach these call sites.
"""
from __future__ import annotations


def profile_of(user):
    """The user's profile, or None when there isn't one."""
    if user is None:
        return None
    # A OneToOne with no row raises rather than returning None, so this cannot
    # be a plain attribute read.
    try:
        return user.profile
    except Exception:
        return None


def avatar_url(user) -> str:
    """
    The account's photo URL, or '' when it has none.

    Empty is the honest answer for "no photo": callers fall back to initials
    rather than to a placeholder image, which is what every surface already did
    before photos existed.
    """
    profile = profile_of(user)
    if profile is None:
        return ''
    return profile.avatar_url or ''


def initials(user) -> str:
    """
    Up to two letters standing in for the account when it has no photo.

    Mirrors ``UserProfile.initials`` but works for an account with no profile
    row, and for no account at all.
    """
    profile = profile_of(user)
    if profile is not None:
        return profile.initials
    if user is None:
        return '?'
    name = (user.get_full_name() or user.get_username() or '').strip()
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return 'U'


def identity(user) -> dict:
    """
    Name, photo and initials for one account, ready to serialise.

    Used by the JSON endpoints so a client renders a person the same way
    wherever that person appears.
    """
    return {
        'name': (user.get_full_name() or user.get_username()) if user else 'Deleted user',
        'avatar': avatar_url(user),
        'initials': initials(user),
    }

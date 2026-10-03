"""
Signing in with a username or with an email address.

Every account in this system is created by an administrator, who types both a
username and an email address into the same form. People then remember the
address they were written to at and type that on the login page, where only the
username worked -- the sign-in simply failed, with nothing on the page saying
which of the two it wanted.

The rule here is deliberately narrow: an email address is resolved to a
username only when exactly one account claims it. Where two accounts share an
address the sign-in is refused rather than guessing which person is at the
keyboard, and where the text is not an address it is passed through untouched,
so a username that happens to contain an "@" still works.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


def resolve_login_name(typed):
    """
    The username for what somebody typed into the login field.

    Returns the text unchanged when it is not an email address, when no account
    has that address, or when more than one does.
    """
    typed = (typed or '').strip()
    if '@' not in typed:
        return typed
    matches = list(
        UserModel._default_manager.filter(email__iexact=typed)
        .values_list(UserModel.USERNAME_FIELD, flat=True)[:2]
    )
    if len(matches) == 1:
        return matches[0]
    return typed


class UsernameOrEmailBackend(ModelBackend):
    """ModelBackend that accepts an email address in place of the username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        # Everything else -- the password check, the timing-safe dummy hash for
        # an unknown account, the is_active rule -- stays with Django.
        return super().authenticate(
            request, username=resolve_login_name(username), password=password, **kwargs
        )

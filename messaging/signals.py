"""
When an account is deleted, its conversations go with it.

A conversation here is between two people. Deleting one of them used to leave
the conversation behind with a single participant, and everyone who had talked
to that person kept a "Deleted user" row in Messages that led nowhere. The
conversation, its messages, and the message notifications pointing at it are
now removed together with the account -- however the account is deleted
(User Management, Django admin, a script).

A conversation with more than two people (none exist yet, but the model allows
them) keeps going without the departed member.
"""
from django.contrib.auth.models import User
from django.db.models.signals import pre_delete
from django.dispatch import receiver


def remove_threads(thread_ids) -> int:
    """Delete these conversations and the message notifications that link to them."""
    from django.urls import reverse
    from notifications.models import Notification

    from .models import Thread

    thread_ids = list(thread_ids)
    if not thread_ids:
        return 0
    inbox = reverse('messaging:inbox')
    links = [f'{inbox}?thread={pk}' for pk in thread_ids]
    Notification.objects.filter(category='message', link__in=links).delete()
    deleted, _ = Thread.objects.filter(pk__in=thread_ids).delete()
    return len(thread_ids)


def orphaned_thread_ids(leaving=None):
    """
    Conversations that have, or are about to have, fewer than two people.

    With `leaving`, the ones that account's deletion will leave behind;
    without, the ones already left behind by earlier deletions.
    """
    from django.db.models import Count

    from .models import Thread

    threads = Thread.objects.annotate(people=Count('participants', distinct=True))
    if leaving is not None:
        return list(threads.filter(participants=leaving, people__lte=2).values_list('pk', flat=True))
    return list(threads.filter(people__lt=2).values_list('pk', flat=True))


@receiver(pre_delete, sender=User, dispatch_uid='messaging.remove_conversations_of_deleted_user')
def remove_conversations_of_deleted_user(sender, instance, **kwargs):
    # Before the delete: afterwards the participant rows are already gone and
    # there is no way left to tell which conversations were this person's.
    remove_threads(orphaned_thread_ids(leaving=instance))


def _remove_attachment_files(sender, instance, **kwargs):
    """
    A deleted attachment row takes its files with it.

    Rows go when a conversation is removed (its account was deleted); without
    this the pictures, recordings and files stayed on disk with nothing that
    referred to them. A message deleted by its sender is only hidden -- its
    row stays for the record -- so this does not run for that.
    """
    for stored in (instance.file, instance.thumbnail):
        try:
            if stored:
                stored.storage.delete(stored.name)
        except Exception:  # pragma: no cover - best effort; the row is already gone
            pass


def _connect_attachment_cleanup():
    from django.db.models.signals import post_delete

    from .models import MessageAttachment
    post_delete.connect(_remove_attachment_files, sender=MessageAttachment,
                        dispatch_uid='messaging.remove_attachment_files')


_connect_attachment_cleanup()

"""
Direct messaging between users of the QA Archiving System.

Any account may message any other active account, in either direction. The system
does not gate who may talk to whom -- people can already reach each other outside
it, and the access control that matters is on documents, which is unchanged.

The one place the system itself could leak is an attached document, so a document
is stored as a real foreign key and resolved per reader at render time. See
``ThreadMessage.visible_document_for``.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Thread(models.Model):
    """
    A conversation between participants.

    Modelled with a many-to-many rather than two `user` columns: a direct message
    is simply a thread with two participants, so adding group conversations later
    needs no migration that rewrites existing rows.
    """

    participants = models.ManyToManyField(User, related_name='message_threads')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [models.Index(fields=['-updated_at'])]

    def __str__(self):
        names = ', '.join(u.get_username() for u in self.participants.all()[:3])
        return f'Thread {self.pk}: {names}'

    # -- lookup ------------------------------------------------------------ #

    @classmethod
    def between(cls, user_a, user_b):
        """
        The existing one-to-one thread for this pair, or None.

        The participant count is checked per candidate rather than with an
        annotation. Chaining two ``filter(participants=...)`` calls adds a second
        join, and a ``Count('participants')`` annotated on top of that counts over
        the joined rows rather than the thread's real membership -- which silently
        returned nothing and created a duplicate thread every time two people
        started a second conversation.
        """
        candidates = (cls.objects
                      .filter(participants=user_a)
                      .filter(participants=user_b)
                      .distinct())
        for thread in candidates:
            if thread.participants.count() == 2:
                return thread
        return None

    @classmethod
    def get_or_create_between(cls, user_a, user_b):
        existing = cls.between(user_a, user_b)
        if existing:
            return existing, False
        thread = cls.objects.create()
        thread.participants.add(user_a, user_b)
        return thread, True

    # -- helpers ----------------------------------------------------------- #

    def other_participant(self, user):
        return self.participants.exclude(pk=user.pk).first()

    def visible_messages(self):
        return self.messages.filter(is_deleted=False)

    def last_message(self):
        return self.visible_messages().order_by('-id').first()

    def unread_count_for(self, user) -> int:
        """
        Messages from someone else since this user last opened the thread.

        Unread is derived from one timestamp per participant rather than a flag on
        every message, so marking a thread read writes a single row instead of one
        per message.
        """
        state = self.read_states.filter(user=user).first()
        qs = self.visible_messages().exclude(sender=user)
        if state and state.last_read_at:
            qs = qs.filter(created_at__gt=state.last_read_at)
        return qs.count()

    def mark_read_for(self, user) -> None:
        ThreadRead.objects.update_or_create(
            thread=self, user=user, defaults={'last_read_at': timezone.now()}
        )

    def touch(self) -> None:
        self.updated_at = timezone.now()
        self.save(update_fields=['updated_at'])


class ThreadMessage(models.Model):
    """One message. May carry a document reference."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                               related_name='sent_messages')
    body = models.TextField(blank=True, default='')
    # A real foreign key, not a pasted link: that is what allows the reference to
    # be permission-checked against whoever is reading it.
    document = models.ForeignKey('documents.Document', on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='message_references')
    created_at = models.DateTimeField(default=timezone.now)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['thread', 'id'])]

    def __str__(self):
        who = self.sender.get_username() if self.sender_id else 'deleted user'
        return f'{who}: {self.body[:40]}'

    def visible_document_for(self, user):
        """
        The attached document, but only if this reader may open it.

        Anyone may mention anything in plain text and the system does not police
        that. A *rendered* reference is different -- that is the software handing
        something over -- so it is checked with the same helper the document detail
        view uses. Readers without access get None, and the template shows a
        placeholder instead of the title.
        """
        if not self.document_id:
            return None
        from accounts.permissions import user_can_access_document

        try:
            if user_can_access_document(user, self.document):
                return self.document
        except Exception:  # pragma: no cover - never break a thread over this
            return None
        return None


class ThreadRead(models.Model):
    """When each participant last opened a thread."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE,
                               related_name='read_states')
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='thread_reads')
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [('thread', 'user')]

    def __str__(self):
        return f'{self.user_id} read {self.thread_id} at {self.last_read_at}'


def unread_total_for(user) -> int:
    """
    Total unread messages across every thread, for the sidebar badge.

    One aggregate rather than a count per thread. This is polled every few
    seconds by every signed-in user on every page, so the old loop -- which ran
    one query per conversation and grew with the number of threads -- was the
    wrong shape for a hot path. The per-participant read stamp is pulled in as a
    correlated subquery; a thread never opened has no stamp, and everything in it
    counts as unread.
    """
    if not getattr(user, 'is_authenticated', False):
        return 0

    last_read = (ThreadRead.objects
                 .filter(thread=models.OuterRef('thread_id'), user=user)
                 .values('last_read_at')[:1])

    return (ThreadMessage.objects
            .filter(thread__participants=user, is_deleted=False)
            .exclude(sender=user)
            .annotate(read_at=models.Subquery(last_read))
            .filter(models.Q(read_at__isnull=True)
                    | models.Q(created_at__gt=models.F('read_at')))
            .count())

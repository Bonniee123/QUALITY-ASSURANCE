"""
Direct messaging between users of the QA Archiving System.

Any account may message any other active account, in either direction. The system
does not gate who may talk to whom -- people can already reach each other outside
it, and the access control that matters is on documents, which is unchanged.

The one place the system itself could leak is an attached document, so a document
is stored as a real foreign key and resolved per reader at render time. See
``ThreadMessage.visible_document_for``.
"""
import os
import uuid

from django.contrib.auth.models import User
from django.db import models, transaction
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
    # Counts every change in the conversation -- a message sent, deleted or
    # reacted to. Each change stamps the message with the new value, so a page
    # asks "what changed since N" and gets every change exactly once, in order.
    change_seq = models.PositiveBigIntegerField(default=0)

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

        Unread is derived from one read mark per participant rather than a flag on
        every message, so marking a thread read writes a single row instead of one
        per message.
        """
        state = self.read_states.filter(user=user).first()
        qs = self.visible_messages().exclude(sender=user)
        if state:
            qs = qs.filter(pk__gt=state.last_read_message_id)
        return qs.count()

    def mark_read_for(self, user, upto=None) -> bool:
        """
        Mark this user as having read every message up to id ``upto`` (default:
        the newest). The mark only moves forward. Returns whether it moved.

        The mark is a message id, not a time: two messages cannot share an id,
        but on Windows a message can share a clock tick with the moment its
        reader last looked, and would then be taken as already read.
        """
        newest = self.messages.aggregate(newest=models.Max('id'))['newest'] or 0
        upto = newest if upto is None else min(upto, newest)
        state, created = ThreadRead.objects.get_or_create(
            thread=self, user=user,
            defaults={'last_read_message_id': upto},
        )
        if created:
            return True
        return bool(
            ThreadRead.objects
            .filter(pk=state.pk, last_read_message_id__lt=upto)
            .update(last_read_message_id=upto, last_read_at=timezone.now())
        )

    def touch(self) -> None:
        self.updated_at = timezone.now()
        self.save(update_fields=['updated_at'])

    def next_seq(self) -> int:
        """
        The next change number for this conversation.

        Call inside the transaction that writes the change. The UPDATE locks the
        thread row until that transaction commits, so a second writer waits for
        the first one's number to become visible together with its change. A
        reader that sees change N therefore also sees every change before N,
        and a page polling "since N" can never skip one.
        """
        assert transaction.get_connection().in_atomic_block, 'next_seq() needs a transaction'
        Thread.objects.filter(pk=self.pk).update(change_seq=models.F('change_seq') + 1)
        self.change_seq = Thread.objects.filter(pk=self.pk).values_list('change_seq', flat=True)[0]
        return self.change_seq


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
    # The answer to a specific earlier message in the same conversation.
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='replies')
    # Made up by the sender's browser for each message it sends. A send that is
    # retried -- the connection dropped before the answer arrived -- carries the
    # same id and gets the message already stored instead of a second copy.
    client_id = models.CharField(max_length=40, null=True, blank=True)
    # The thread's change number when this message last changed (sent,
    # deleted, reacted to). See Thread.next_seq.
    change_seq = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['thread', 'id']),
            models.Index(fields=['thread', 'change_seq']),
        ]
        constraints = [
            # NULL client ids (messages from before this existed) never clash.
            models.UniqueConstraint(fields=['sender', 'client_id'], name='unique_message_client_id'),
        ]

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
    """How far each participant has read a thread, and when they got there."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE,
                               related_name='read_states')
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='thread_reads')
    last_read_message_id = models.PositiveBigIntegerField(default=0)
    last_read_at = models.DateTimeField(default=timezone.now)
    # Set a few seconds ahead while this participant is typing; "X is typing"
    # shows while it is in the future. Kept in the database, not in a cache, so
    # it holds across server processes.
    typing_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('thread', 'user')]

    def __str__(self):
        return (f'{self.user_id} read {self.thread_id} up to message '
                f'{self.last_read_message_id}')


def _attachment_path(instance, filename):
    """A random stored name: the original is kept in `original_name` for display only."""
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"message_attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class MessageAttachment(models.Model):
    """
    A file sent in a message: a picture, a voice message, or any other file.

    Stored under media/, which is never served directly (BlockPublicMediaMiddleware);
    the attachment view hands it only to the conversation's participants.
    """

    KIND_IMAGE = 'image'
    KIND_VOICE = 'voice'
    KIND_FILE = 'file'
    KIND_CHOICES = [(KIND_IMAGE, 'Image'), (KIND_VOICE, 'Voice message'), (KIND_FILE, 'File')]

    message = models.ForeignKey(ThreadMessage, on_delete=models.CASCADE, related_name='attachments')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    file = models.FileField(upload_to=_attachment_path, max_length=255)
    # A smaller copy of a picture for the conversation, re-encoded -- which also
    # drops the photo's metadata (camera, location) from what the reader loads.
    thumbnail = models.FileField(upload_to=_attachment_path, max_length=255, blank=True)
    original_name = models.CharField(max_length=255)
    # Decided by the server from the file's content, never taken from the browser.
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # seconds, voice messages
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.kind}: {self.original_name}'


class MessageReaction(models.Model):
    """One person's emoji on one message. A second click on the same emoji takes it back."""

    message = models.ForeignKey(ThreadMessage, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='message_reactions')
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['message', 'user', 'emoji'], name='unique_reaction'),
        ]

    def __str__(self):
        return f'{self.user_id} {self.emoji} on {self.message_id}'


def unread_total_for(user) -> int:
    """
    Total unread messages across every thread, for the sidebar badge.

    One aggregate rather than a count per thread. This is polled every few
    seconds by every signed-in user on every page, so the old loop -- which ran
    one query per conversation and grew with the number of threads -- was the
    wrong shape for a hot path. The per-participant read mark is pulled in as a
    correlated subquery; a thread never opened has no mark, and everything in it
    counts as unread.
    """
    if not getattr(user, 'is_authenticated', False):
        return 0

    last_read = (ThreadRead.objects
                 .filter(thread=models.OuterRef('thread_id'), user=user)
                 .values('last_read_message_id')[:1])

    return (ThreadMessage.objects
            .filter(thread__participants=user, is_deleted=False)
            .exclude(sender=user)
            .annotate(read_upto=models.Subquery(last_read))
            .filter(models.Q(read_upto__isnull=True)
                    | models.Q(pk__gt=models.F('read_upto')))
            .count())

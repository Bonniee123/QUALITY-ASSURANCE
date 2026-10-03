"""Chatbot FAQ model, plus persisted QA Archive Agent conversations."""
import re

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class ChatbotFAQ(models.Model):
    """Stores predefined questions and answers for the rule-based chatbot."""

    # No 'tracker' category: the Missing Document Tracker was removed from the
    # system, and FAQs describing it were deleted in migration 0002.
    CATEGORY_CHOICES = [
        ('upload', 'Uploading'),
        ('search', 'Searching'),
        ('mapping', 'Evidence Mapping'),
        ('areas', 'Area Submissions'),
        ('ai', 'Document Analysis'),
        ('general', 'General'),
    ]

    question = models.CharField(max_length=500)
    answer = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    keywords = models.JSONField(default=list, blank=True, help_text='Keywords for matching user queries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'question']
        verbose_name = 'Chatbot FAQ'
        verbose_name_plural = 'Chatbot FAQs'

    def __str__(self):
        return self.question


class Conversation(models.Model):
    """
    One thread with the QA Archive Agent.

    Threads are per-user: the conversation list, its titles and its messages are
    only ever readable by the account that created them, because a QA thread can
    quote document titles the other roles are not scoped to see.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='qa_conversations')
    title = models.CharField(max_length=120, default='New conversation')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-updated_at', '-id']
        verbose_name = 'Agent conversation'
        verbose_name_plural = 'Agent conversations'
        indexes = [models.Index(fields=['user', '-updated_at'])]

    def __str__(self):
        return f'{self.user_id}: {self.title}'

    # -- title ------------------------------------------------------------- #

    _TITLE_NOISE = {
        'find', 'show', 'me', 'the', 'a', 'an', 'all', 'get', 'give', 'list',
        'please', 'can', 'you', 'i', 'need', 'want', 'do', 'we', 'have', 'what',
        'which', 'are', 'is', 'there', 'any', 'related', 'to', 'about', 'from',
        'in', 'of', 'and', 'or', 'with', 'for', 'my', 'our', 'us', 'how',
    }

    @classmethod
    def title_from(cls, message: str) -> str:
        """
        Derive a useful thread name from the opening question.

        "Find accreditation documents from 2025." becomes "Accreditation
        Documents 2025" -- the words that carry the subject, capitalised, with
        the filler removed. Falls back to a trimmed version of the message when
        nothing survives the filter.
        """
        words = re.findall(r"[A-Za-z0-9]+", message or '')
        kept = [w for w in words if w.lower() not in cls._TITLE_NOISE]
        if not kept:
            kept = words
        if not kept:
            return 'New conversation'
        title = ' '.join(w.upper() if w.isupper() and len(w) <= 5 else w.capitalize()
                         for w in kept[:6])
        return title[:120]

    def touch_title(self, first_message: str) -> None:
        if self.title in ('', 'New conversation'):
            self.title = self.title_from(first_message)

    @property
    def preview(self) -> str:
        last = self.messages.order_by('-id').first()
        return (last.text[:80] if last else '')


class Message(models.Model):
    """A single turn. Agent turns keep their cards and actions in `payload`."""

    USER = 'user'
    AGENT = 'agent'
    ROLE_CHOICES = [(USER, 'User'), (AGENT, 'Agent')]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                     related_name='messages')
    role = models.CharField(max_length=8, choices=ROLE_CHOICES)
    text = models.TextField(blank=True, default='')
    # Cards and actions are rendered from this rather than re-derived, so
    # reopening a thread shows exactly what the agent showed at the time.
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['conversation', 'id'])]

    def __str__(self):
        return f'{self.role}: {self.text[:40]}'

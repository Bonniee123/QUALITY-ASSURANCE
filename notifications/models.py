"""In-app notifications for QA users."""
from django.db import models
from django.contrib.auth.models import User


class Notification(models.Model):
    """A single notification delivered to a user."""

    CATEGORY_CHOICES = [
        ('evidence', 'Evidence Mapping'),
        ('duplicate', 'Duplicate Detected'),
        ('completion', 'Requirement Completed'),
        ('upload', 'Upload'),
        ('message', 'Direct Message'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system')
    message = models.CharField(max_length=400)
    link = models.CharField(max_length=400, blank=True, default='')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'is_read'])]

    def __str__(self):
        return f"{self.user.username}: {self.message[:60]}"

    @property
    def display_message(self):
        from .user_messages import display_notification_message
        return display_notification_message(self.message)

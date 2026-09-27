"""
Models for QA requirements and evidence mapping.
"""
import os

from django.db import models
from django.contrib.auth.models import User


class QAProgram(models.Model):
    """
    Top-level QA program (audit cycle) — e.g. "Accreditation", "ISO Internal Quality Audit".
    Sits above QA Area / Criterion / Indicator and lets us scope every requirement,
    document, and dashboard view by program.
    """
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(
        max_length=20, unique=True,
        help_text='Short identifier shown on badges, e.g. "ISO-IQA".',
    )
    description = models.TextField(blank=True, default='')
    color = models.CharField(
        max_length=30, default='hsl(215, 65%, 50%)',
        help_text='CSS color used for badges and progress bars.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def requirement_count(self):
        return self.requirements.count()

    @property
    def document_count(self):
        return self.documents.count()


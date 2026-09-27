"""
Accreditation areas.

This app once modelled a five-level AACCUP hierarchy -- area, parameter,
category, indicator, required evidence -- with a page for maintaining each
level. Not one document in the system was ever classified below the area, so
the four deeper levels were removed as out of scope: the system exists so
faculty can upload documents and QA can review them.

The area itself is kept, and is not really accreditation structure at all: it
is the access boundary. A faculty account is assigned areas and sees only
documents in them, while QA and admin see everything. It also backs the
repository area filter, reports, search and the area lookup in Messages.
"""
from django.db import models
from django.utils import timezone


class AccreditationArea(models.Model):
    """Top-level accreditation area (e.g. Area I – Vision, Mission, …)."""
    area_code = models.CharField(
        max_length=32,
        unique=True,
        help_text='e.g. "Area I"',
    )
    area_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['area_code']
        verbose_name = 'Accreditation Area'
        verbose_name_plural = 'Accreditation Areas'

    def __str__(self):
        return f'{self.area_code}: {self.area_name}'

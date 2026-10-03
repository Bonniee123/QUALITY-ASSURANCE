"""
Document and related models for the archiving system.
Stores uploaded documents, AI processing results, cluster info, and activity logs.
"""
import hashlib
import logging
import os

from django.db import models
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class DocumentQuerySet(models.QuerySet):
    """
    Reading a soft-deleted archive without having to remember to.

    The default manager is left unfiltered on purpose. A manager that silently
    hid deleted rows would also hide them from the undo that has to find them
    again, and from anyone trying to work out where a document went. Saying
    `.live()` at each listing is one word, and it says what it means.
    """

    def live(self):
        """Documents a user should see: not deleted."""
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        """Documents removed by a person and still recoverable."""
        return self.filter(deleted_at__isnull=False)


class Document(models.Model):
    """Core document model storing file, metadata, and AI processing results."""

    objects = DocumentQuerySet.as_manager()

    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('docx', 'DOCX'),
        ('xlsx', 'XLSX'),
        ('jpg', 'JPG'),
        ('jpeg', 'JPEG'),
        ('png', 'PNG'),
    ]

    EVIDENCE_STATUS_CHOICES = [
        ('unmapped', 'Unmapped'),
        ('suggested', 'Suggested'),
        ('confirmed', 'Confirmed'),
        ('needs_review', 'Needs Review'),
    ]

    DUPLICATE_STATUS_CHOICES = [
        ('none', 'No Duplicate'),
        ('pending_check', 'Pending Duplicate Check'),
        ('possible', 'Possible Duplicate'),
        ('confirmed_dup', 'Confirmed Duplicate'),
    ]
    OCR_STATUS_CHOICES = [
        ('not_run', 'Not Run'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
    ]

    # Core metadata
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='uploaded_documents/%Y/%m/')
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    year = models.IntegerField()
    document_type = models.CharField(max_length=100, help_text='e.g., Policy, Report, Manual, Form')
    qa_area = models.CharField(max_length=200, blank=True, default='')
    criterion = models.CharField(max_length=200, blank=True, default='')
    indicator = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')

    # Upload info
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='documents')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # QA program scope (e.g. "Accreditation", "ISO Internal Quality Audit") — optional
    program = models.ForeignKey(
        'qa_mapping.QAProgram', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documents',
        help_text='Which QA program / audit cycle this document was uploaded for.',
    )

    # AI processing results
    extracted_text = models.TextField(blank=True, default='')
    ocr_text = models.TextField(blank=True, default='')
    image_phash = models.CharField(max_length=64, blank=True, default='', help_text='Perceptual hash (dHash) for visual near-duplicate detection of images.')
    content_sha256 = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        help_text='SHA-256 of the stored file. Lets exact-duplicate upload checks '
                  'run as one indexed query instead of re-hashing every file on disk.',
    )
    tfidf_keywords = models.JSONField(default=list, blank=True)
    cluster_label = models.IntegerField(null=True, blank=True)
    duplicate_status = models.CharField(max_length=20, choices=DUPLICATE_STATUS_CHOICES, default='none')
    similar_documents = models.JSONField(default=list, blank=True)
    ocr_status = models.CharField(max_length=20, choices=OCR_STATUS_CHOICES, default='not_run')
    ocr_error = models.TextField(blank=True, default='')
    recommendation = models.TextField(blank=True, default='')
    evidence_status = models.CharField(max_length=20, choices=EVIDENCE_STATUS_CHOICES, default='unmapped')

    # Processing status
    is_processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, default='')
    is_archived = models.BooleanField(
        default=False,
        help_text='True if this is an older version superseded by a newer upload.',
    )
    # Deletion is not the same event as being superseded, so it does not share
    # that flag. `is_archived` says "a newer upload replaced this"; the
    # timestamp below says "a person removed this, at this moment".
    #
    # Keeping them apart is what makes undo possible. After a bulk delete the
    # rows to restore are exactly those carrying a `deleted_at`, and the two
    # genuinely superseded manuscript versions are left alone. Sharing one flag
    # would put both in the same bucket with no way to tell them apart again.
    deleted_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text='Set when a user deletes this document; null means not deleted. '
                  'Clearing it restores the document.',
    )

    # The accreditation area a document belongs to.
    #
    # This used to be the top of a five-level hierarchy -- area, parameter,
    # category, indicator, required evidence -- which the upload form asked
    # people to fill in one dropdown at a time. Not one of the 27 documents in
    # the system was ever classified below this level, so the four deeper fields
    # and their pages were removed as out of scope: the system's job is faculty
    # upload and QA review, not modelling an accreditation manual.
    #
    # The area itself stays because it is the access boundary. A faculty account
    # is assigned areas and sees only documents in them; QA and admin see all.
    # See accounts.permissions.scope_documents_for_user.
    acc_area = models.ForeignKey(
        'qa_structure.AccreditationArea', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='documents',
    )

    # Document versioning — points to the document this one supersedes (or None)
    previous_version = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='superseded_by',
        help_text='If this document replaces an older one, link it here.',
    )

    class Meta:
        # '-id' is the tie-break. Documents saved in the same instant - which is what
        # a bulk upload does - share an uploaded_at value, and with only the timestamp
        # to order by the database is free to return those rows in any order. Adding
        # the descending primary key makes every listing deterministic and puts the
        # most recently uploaded document first.
        ordering = ['-uploaded_at', '-id']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """
        Save, then fill content_sha256 once the file exists on disk.

        The hash has to be computed after super().save() because that is what writes
        the upload to storage. It is stored so the exact-duplicate check on upload is
        a single indexed query instead of re-reading every file in the repository.
        """
        super().save(*args, **kwargs)
        if not self.content_sha256:
            self.ensure_content_hash()

    def ensure_content_hash(self):
        """Compute and persist content_sha256 if absent. Returns the hash or ''."""
        if self.content_sha256:
            return self.content_sha256
        if not self.file:
            return ''
        try:
            path = self.file.path
        except (ValueError, NotImplementedError):
            return ''
        if not os.path.exists(path):
            return ''
        hasher = hashlib.sha256()
        try:
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    hasher.update(chunk)
        except OSError as exc:
            logger.warning('Could not hash %s for document %s: %s', path, self.pk, exc)
            return ''
        digest = hasher.hexdigest()
        self.content_sha256 = digest
        # update() rather than save() so this never recurses back into save().
        type(self).objects.filter(pk=self.pk).update(content_sha256=digest)
        return digest

    @property
    def filename(self):
        return os.path.basename(self.file.name) if self.file else ''

    @property
    def combined_text(self):
        """Return combined extracted and OCR text for AI processing."""
        return f"{self.extracted_text} {self.ocr_text}".strip()

    @property
    def processing_in_progress(self):
        """
        True only while upload ingest is still running (no text yet, no failure flag).
        Do not rely on is_processed alone — light AI / clustering may leave that flag stale.
        """
        if self.is_processed:
            return False
        if (self.processing_error or '').strip():
            return False
        if self.combined_text:
            return False
        return True

    def version_chain(self):
        """Return list of all versions oldest-first (including this one)."""
        chain = []
        seen = set()
        node = self
        while node and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.previous_version
        chain.reverse()
        node = self.superseded_by.first() if self.pk else None
        while node and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.superseded_by.first()
        return chain

    @property
    def latest_version(self):
        """Walk forward through superseded_by to find the newest version."""
        node = self
        seen = {self.pk}
        nxt = self.superseded_by.first() if self.pk else None
        while nxt and nxt.pk not in seen:
            seen.add(nxt.pk)
            node = nxt
            nxt = nxt.superseded_by.first()
        return node


class ClusterResultQuerySet(models.QuerySet):
    """
    Cluster rows that still describe something a reader can open.

    A hard delete used to take these rows with it, because the foreign key
    cascades. A soft delete leaves them behind, and every cluster card names
    itself after the newest row for its number -- so a deleted document went
    on lending its title to a cluster it was no longer part of.
    """

    def live(self):
        return self.filter(document__deleted_at__isnull=True)


class ClusterResult(models.Model):
    """Stores cluster assignment and top keywords per document."""

    objects = ClusterResultQuerySet.as_manager()

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='cluster_results')
    cluster_number = models.IntegerField()
    cluster_label = models.CharField(max_length=100, blank=True, default='')
    top_keywords = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Cluster {self.cluster_number} - {self.document.title}"


class ActivityLog(models.Model):
    """Tracks user actions throughout the system."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='activity_logs')
    action = models.CharField(max_length=50)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.action} at {self.created_at}"


class BackgroundJob(models.Model):
    JOB_TYPE_CHOICES = [
        ('full_ai_pipeline', 'Full AI Pipeline'),
        ('light_post_upload', 'Light Post Upload'),
        ('bulk_upload_process', 'Bulk Upload Process'),
        ('refresh_duplicate_flags', 'Refresh Duplicate Flags'),
        ('reprocess_ocr', 'Reprocess OCR'),
        ('reindex_search_artifacts', 'Reindex Search Artifacts'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payload = models.JSONField(default=dict, blank=True)
    result = models.TextField(blank=True, default='')
    error = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='background_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.job_type} [{self.status}]'


class ProcessingMetric(models.Model):
    metric_name = models.CharField(max_length=64)
    metric_value = models.FloatField()
    unit = models.CharField(max_length=20, blank=True, default='')
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

"""
Deleting documents, undoing a deletion, and making a deletion permanent.

Every delete goes through here, so the rules live in one place:

* A delete is a DeletionBatch. A single delete is confirmed by the person
  first and is permanent at once; a bulk delete stays undoable for
  UNDO_SECONDS, and each bulk delete has its own batch and its own expiry, so
  a second bulk delete never resets or replaces the first.
* The server decides who may delete and restore, per document, at the moment
  of the request -- never a list of ids the browser vouches for.
* Nothing that says who uploaded or deleted a document is ever removed. The
  document row stays, its history (ActivityLog rows that name it) stays, and
  only the file is removed when the deletion becomes permanent.
* A batch leaves PENDING by a conditional UPDATE, so an undo and an expiry
  that arrive at the same moment cannot both act on it.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.permissions import user_can_modify_document

from .audit import person_name, record_document_event
from .models import ActivityLog, DeletionBatch, Document

logger = logging.getLogger(__name__)


def undo_seconds() -> int:
    return int(getattr(settings, 'DELETE_UNDO_SECONDS', 10))


def undo_grace_seconds() -> int:
    """Allowance for the click that leaves the browser in the last second to reach the server."""
    return int(getattr(settings, 'DELETE_UNDO_GRACE_SECONDS', 3))


class DeletionError(Exception):
    """A deletion or undo that could not be done; `code` says why, for the interface."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Deleting
# --------------------------------------------------------------------------- #

def deletable(user, ids):
    """The live documents among `ids` that this user may delete, and how many were refused."""
    wanted = {int(i) for i in ids}
    candidates = list(Document.objects.live().filter(pk__in=wanted).select_related('acc_area', 'uploaded_by'))
    allowed = [doc for doc in candidates if user_can_modify_document(user, doc)]
    return allowed, len(wanted) - len(allowed)


def delete_documents(user, documents, *, kind, request=None) -> DeletionBatch:
    """
    Delete `documents` (already permission-checked) as one batch.

    A single delete is final immediately: the person confirmed it in a dialog
    first. A bulk delete stays pending until it is undone or expires.
    """
    from .ai_pipeline import forget_deleted_matches

    documents = list(documents)
    if not documents:
        raise DeletionError('nothing', 'No documents were deleted.')
    now = timezone.now()
    ids = [doc.pk for doc in documents]
    with transaction.atomic():
        batch = DeletionBatch.objects.create(
            user=user, user_name=person_name(user), kind=kind,
            document_ids=ids, document_count=len(ids),
            created_at=now,
            expires_at=now if kind == DeletionBatch.KIND_SINGLE else now + timedelta(seconds=undo_seconds()),
        )
        # live() again inside the transaction: a document deleted by someone
        # else a moment ago is not deleted twice or counted in this batch.
        stamped = Document.objects.live().filter(pk__in=ids).update(
            deleted_at=now, deleted_by=user, deletion_batch=batch,
        )
        if stamped != len(ids):
            ids = list(Document.objects.filter(deletion_batch=batch).values_list('pk', flat=True))
            documents = [doc for doc in documents if doc.pk in set(ids)]
            batch.document_ids, batch.document_count = ids, len(ids)
            batch.save(update_fields=['document_ids', 'document_count'])
            if not ids:
                raise DeletionError('gone', 'Those documents were already deleted.')

        action = 'delete_document' if kind == DeletionBatch.KIND_SINGLE else 'bulk_delete_document'
        for doc in documents:
            record_document_event(
                doc, action, user, request=request, batch=batch,
                description=(f'Deleted document: {doc.title} (uploaded by {_uploader(doc)})'
                             + ('' if kind == DeletionBatch.KIND_SINGLE
                                else f' — bulk delete of {len(ids)}, undo available for {undo_seconds()} s')),
            )

    forget_deleted_matches(ids)
    for doc in documents:
        if doc.previous_version_id and doc.previous_version_id not in ids:
            restore_orphaned_version(doc.previous_version_id, user)

    if kind == DeletionBatch.KIND_SINGLE:
        finalize_batch(batch)
        batch.refresh_from_db()
    return batch


def _uploader(doc) -> str:
    return person_name(doc.uploaded_by) or 'a removed account'


def restore_orphaned_version(older_pk, user):
    """
    Bring back the older version of a document that was just deleted.

    It was archived only because the deleted document replaced it; left
    archived, nothing pointed at it any more and no page could reach it.
    """
    if not older_pk:
        return
    older = Document.objects.filter(pk=older_pk, is_archived=True).first()
    # A deleted successor does not count as one: deletion stamps the row, so a
    # plain `.exists()` would still find the document that was just deleted.
    if older is None or older.superseded_by.filter(deleted_at__isnull=True).exists():
        return
    older.is_archived = False
    older.save(update_fields=['is_archived'])
    ActivityLog.objects.create(
        user=user, actor_name=person_name(user), action='version_unarchive',
        document=older, document_title=older.title[:255],
        description=f'Restored "{older.title}": the newer version that replaced it was deleted.',
    )


# --------------------------------------------------------------------------- #
# Undoing
# --------------------------------------------------------------------------- #

def pending_batches_for(user):
    """This user's deletions that can still be undone, oldest first."""
    cutoff = timezone.now()
    return list(DeletionBatch.objects.filter(
        user=user, status=DeletionBatch.STATUS_PENDING, expires_at__gt=cutoff,
    ).order_by('created_at'))


def undo_batch(user, batch_id, *, request=None):
    """
    Restore what one batch deleted. Returns (batch, restored, refused).

    Only the person who deleted may undo, only while the batch is pending and
    inside its window, and only documents they may still manage: someone whose
    area assignment changed in the meantime gets back what they may still
    edit, and the rest stays deleted.
    """
    batch = DeletionBatch.objects.filter(pk=batch_id).first()
    if batch is None or batch.user_id != getattr(user, 'pk', None):
        raise DeletionError('not_found', 'That deletion cannot be undone from this account.')
    deadline = timezone.now() - timedelta(seconds=undo_grace_seconds())
    with transaction.atomic():
        # The claim. Exactly one of undo and finalize moves a batch out of
        # PENDING; whichever loses sees 0 rows and stops.
        claimed = DeletionBatch.objects.filter(
            pk=batch.pk, status=DeletionBatch.STATUS_PENDING, expires_at__gt=deadline,
        ).update(status=DeletionBatch.STATUS_RESTORED, restored_at=timezone.now())
        if not claimed:
            batch.refresh_from_db()
            if batch.status == DeletionBatch.STATUS_RESTORED:
                raise DeletionError('already_restored', 'These documents were already restored.')
            raise DeletionError('expired', 'The time to undo this deletion has passed.')

        docs = list(Document.objects.filter(deletion_batch=batch, deleted_at__isnull=False, purged_at__isnull=True)
                    .select_related('acc_area'))
        allowed = [d for d in docs if user_can_modify_document(user, d, allow_deleted=True)]
        refused = [d for d in docs if d not in allowed]
        if allowed:
            Document.objects.filter(pk__in=[d.pk for d in allowed]).update(deleted_at=None, deleted_by=None)
            # A restored document supersedes its predecessor again.
            older = [d.previous_version_id for d in allowed if d.previous_version_id]
            if older:
                Document.objects.filter(pk__in=older).update(is_archived=True)
        for doc in allowed:
            record_document_event(doc, 'restore_document', user, request=request, batch=batch,
                                  description=f'Restored document (undo): {doc.title}')
        batch.restored_count = len(allowed)
        batch.save(update_fields=['restored_count'])

    # What this person may no longer manage stays deleted, and nothing will
    # come back for it: it is made permanent now rather than left hanging.
    if refused:
        _purge_documents(refused, batch)
    return batch, len(allowed), len(refused)


# --------------------------------------------------------------------------- #
# Making it permanent
# --------------------------------------------------------------------------- #

def finalize_expired_batches(now=None) -> int:
    """
    Make every expired pending batch permanent. Returns how many were finalized.

    Called on every live-update poll and before each delete or undo, so it runs
    within seconds of a window closing while anyone is using the system, and by
    the `finalize_deletions` command for a schedule. Correctness never waits on
    it: an expired batch cannot be undone whether or not this has run yet.
    """
    deadline = (now or timezone.now()) - timedelta(seconds=undo_grace_seconds())
    done = 0
    for batch in DeletionBatch.objects.filter(status=DeletionBatch.STATUS_PENDING, expires_at__lte=deadline):
        if finalize_batch(batch):
            done += 1
    return done


def finalize_legacy_deletions() -> int:
    """
    Make permanent the deletions made before batches existed.

    The earlier version stamped `deleted_at` and kept the file indefinitely.
    Those rows have no batch and so no undo window that could ever close;
    this gives them one finalized batch, removes their files, and records it
    in each one's history. Run on request only (`finalize_deletions
    --include-legacy`): it removes files, so it is never done implicitly.
    """
    docs = list(Document.objects.filter(deleted_at__isnull=False, purged_at__isnull=True, deletion_batch__isnull=True))
    if not docs:
        return 0
    now = timezone.now()
    batch = DeletionBatch.objects.create(
        user=None, user_name='an earlier version of the system', kind=DeletionBatch.KIND_BULK,
        status=DeletionBatch.STATUS_FINALIZED, document_ids=[d.pk for d in docs],
        document_count=len(docs), expires_at=now, finalized_at=now,
    )
    Document.objects.filter(pk__in=[d.pk for d in docs]).update(deletion_batch=batch)
    _purge_documents(docs, batch)
    return len(docs)


def finalize_batch(batch) -> bool:
    """Remove the files of a batch's still-deleted documents and record it. False if it was not pending."""
    claimed = DeletionBatch.objects.filter(pk=batch.pk, status=DeletionBatch.STATUS_PENDING).update(
        status=DeletionBatch.STATUS_FINALIZED, finalized_at=timezone.now(),
    )
    if not claimed:
        return False
    docs = list(Document.objects.filter(deletion_batch=batch, deleted_at__isnull=False, purged_at__isnull=True))
    _purge_documents(docs, batch)
    _notify_deleted(batch, docs)
    return True


def _purge_documents(docs, batch):
    """
    Remove the files; keep the rows.

    The file goes first and the row is marked after, so a failure part-way
    leaves a deleted document whose file still exists -- recoverable by an
    administrator -- and never a live document whose file is gone.
    """
    from .preview_service import clear_preview_cache

    for doc in docs:
        name = doc.original_filename or (doc.file.name.rsplit('/', 1)[-1] if doc.file else '')
        try:
            if doc.file:
                doc.file.delete(save=False)
            clear_preview_cache(doc)
        except Exception as exc:  # pragma: no cover - depends on the file system
            logger.error('Could not remove the file of deleted document %s: %s', doc.pk, exc)
            continue
        Document.objects.filter(pk=doc.pk).update(
            purged_at=timezone.now(), file='', original_filename=name[:255],
        )
        record_document_event(
            doc, 'purge_document', None, batch=batch,
            description=(f'Permanently deleted: {doc.title} ({name}) — deleted by {batch.user_name}, '
                         f'uploaded by {_uploader(doc)}'),
        )


def _notify_deleted(batch, docs):
    """
    "Document Deleted — Faculty B deleted Report.pdf", once, to Administrators and QA Heads.

    Sent when a deletion becomes permanent, so an undone deletion never
    produces a notification about a document that is back, and a notification
    never points at something that was restored. The batch id makes the
    notification key, so processing a batch twice cannot notify twice.
    """
    if not docs:
        return
    from django.urls import reverse
    from notifications.services import notify_qa_staff

    who = batch.user_name or 'Someone'
    if len(docs) == 1:
        message = f'Document Deleted — {who} deleted "{docs[0].title}"'
    else:
        message = f'Documents Deleted — {who} deleted {len(docs)} documents'
    notify_qa_staff(
        message, category='deletion', link=reverse('accounts:document_history'),
        dedupe_key=f'deleted:{batch.pk}', exclude=batch.user,
    )

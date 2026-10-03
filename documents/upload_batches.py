"""
Server-side state for an upload batch.

The upload page used to show progress from a job id kept in ``sessionStorage``,
which had two consequences. It was lost to anything but same-tab navigation --
a refresh in a new tab, another device, or a fresh login showed nothing. And it
tracked ``bulk_upload_process``, the job that *saves the files*, which finishes
in seconds; the analysis that follows is a separate ``full_ai_pipeline`` job. So
the panel cleared itself while the repository still said "processing", and the
batch looked as though it had vanished.

Everything here is derived from rows the server already owns -- the batch job and
the documents it produced -- so the same answer comes back on any device, in any
tab, after any reload, for as long as the job row exists.

A file's state is read from the document, not from the job: the job only knows
that a file was saved, while the document knows whether it has been through
extraction, duplicate detection and clustering.
"""
from __future__ import annotations

import re

from django.urls import reverse

import os
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import BackgroundJob, Document

# A document that has not reached a terminal state in this long is reported as
# stalled rather than left spinning. A full pipeline over ~100 documents takes
# well under a minute, so ten minutes is far past "just slow".
STALL_AFTER = timedelta(minutes=10)

# How long a *finished* batch stays on the upload page. Unfinished work is shown
# regardless of age -- that is the whole point -- but a batch that has settled
# is a result, and results belong in the Repository.
#
# Six hours meant a batch uploaded in the morning was still pinned under the
# drop zone in the afternoon. Half an hour covers coming back to the page to
# check on an upload; after that the summary is history, and the page says so by
# linking to the Repository. The panel also clears itself ten seconds after it
# settles while the page is open, so this only decides what a later visit sees.
KEEP_FINISHED_FOR = timedelta(minutes=30)

BATCH_JOB_TYPES = ('bulk_upload_process',)


def _file_state(doc: Document) -> str:
    """
    Terminal or in-flight state for one uploaded document.

    Ordering matters: an error is worth reporting even on a document that also
    looks like a duplicate, and a duplicate is worth reporting before the
    generic "done".
    """
    if (doc.processing_error or '').strip():
        return 'failed'
    if doc.duplicate_status in ('possible', 'confirmed_dup'):
        return 'duplicate'
    # 'pending_check' means duplicate detection has not reached this document
    # yet, so the pipeline is not finished with it even if the text is in.
    if doc.duplicate_status == 'pending_check' or doc.processing_in_progress:
        return 'processing'
    return 'completed'


def _match_name(user, match: dict) -> str:
    """
    How a batch row names the document its file matched.

    Only by title when the uploader may open that document: a Faculty member's
    row used to show the title of a match in another area.
    """
    from accounts.permissions import faculty_area_scope, user_can_access_document

    from .near_duplicates import document_label

    title = document_label(match.get('title'))
    if user is None or faculty_area_scope(user) is None:
        return title
    matched = Document.objects.filter(pk=match.get('id')).first()
    if matched is not None and user_can_access_document(user, matched):
        return title
    return 'a document already in the archive'


def _analysis_pending(payload: dict):
    """
    Whether the clustering run that covers this batch is still to finish.

    Clustering and duplicate review run once per batch, after every file's text
    is in, as a separate job. The batch records when it asked for that run; any
    run that *started* after then read this batch's documents. Returns
    ``(pending, requested_at)``. Batches from before this existed carry no
    timestamp and are treated as analysed, as they always were.
    """
    requested = parse_datetime(payload.get('analysis_requested_at') or '')
    if requested is None:
        return False, None
    done = BackgroundJob.objects.filter(
        job_type='full_ai_pipeline',
        status__in=('completed', 'failed'),
        started_at__gte=requested,
    ).exists()
    return (not done), requested


def _stalled(state: str, since) -> bool:
    return state in ('processing', 'queued') and bool(since) and (
        timezone.now() - since > STALL_AFTER
    )


def _current_reason(reason) -> str:
    """
    A stored rejection reason, read back in the wording the system uses now.

    Batches refused before the message was rewritten recorded "Near-duplicate
    content detected", which said nothing about the file having been discarded.
    The stored row is left alone; only what the reader sees is brought up to
    date, as `display_notification_message` does for notifications.
    """
    from .near_duplicates import document_label

    text = (reason or '').strip()
    if not text:
        return 'Not uploaded — already in the archive.'
    if not text.startswith('Near-duplicate content detected'):
        return text

    match = re.search(r'very similar to (.+?)\)?$', text)
    named = match.group(1).rstrip(')').strip() if match else ''
    # The old message cut the title at sixty characters, so a stored reason can
    # end mid-word inside its own quotation marks. Re-wrap it the current way.
    stripped = named.strip('“”"').strip()
    if not stripped or stripped == 'a document already in the archive':
        # The match was one this reader may not open, so it was never named.
        return 'Not uploaded — identical content to a document already in the archive.'
    return (f'Not uploaded — identical content to {document_label(stripped)}, '
            f'already in the archive.')


def batch_detail(job: BackgroundJob) -> dict:
    """One batch: per-file rows plus the counts the summary bar needs."""
    payload = job.payload or {}
    doc_ids = list(payload.get('document_ids') or [])
    total = int(payload.get('total_count') or len(doc_ids) or 0)
    job_errors = {str(e.get('filename') or ''): e.get('error') or ''
                  for e in (payload.get('errors') or []) if isinstance(e, dict)}
    # Uploads removed after extraction because their text duplicated an existing
    # document -- the check the upload request used to make before saving.
    rejected = payload.get('rejected') or {}

    documents = {d.pk: d for d in Document.objects.filter(pk__in=doc_ids)}

    files = []
    for pk in doc_ids:
        doc = documents.get(pk)
        if doc is None and str(pk) in rejected:
            info = rejected[str(pk)] or {}
            # The refused file has no row of its own, but the document it
            # matched does, so the reader can go and look at it.
            match_id = info.get('match_id')
            files.append({'name': info.get('name') or f'document-{pk}', 'state': 'duplicate',
                          'detail': _current_reason(info.get('reason'))[:200],
                          'document_id': None, 'url': None, 'stalled': False,
                          'match_id': match_id,
                          'match_url': (reverse('documents:detail', args=[match_id])
                                        if match_id else None)})
            continue
        if doc is None:
            # The row was created and has since been deleted. That is not a
            # failed upload -- the upload worked -- so it gets its own neutral
            # state. Calling it "failed" made an old, tidied-up batch look like
            # something had gone wrong.
            files.append({'name': f'document-{pk}', 'state': 'removed',
                          'detail': 'Deleted from the repository since upload.',
                          'document_id': None, 'url': None, 'stalled': False})
            continue

        state = _file_state(doc)
        name = os.path.basename(doc.file.name) if doc.file else (doc.title or f'document-{pk}')
        detail = ''
        if state == 'failed':
            detail = (doc.processing_error or '').strip()[:200]
        elif state == 'duplicate':
            # This file was kept. It is only flagged, and a person decides.
            # The refused files above say "Not uploaded" instead, so the two
            # outcomes never wear the same words.
            similar = doc.similar_documents or []
            if similar:
                first = similar[0]
                pct = round(float(first.get('similarity') or 0) * 100)
                detail = (f"Needs review — {pct}% similar to "
                          f"{_match_name(job.created_by, first)}")
            else:
                detail = 'Needs review — flagged as a possible duplicate.'
        files.append({
            'name': name,
            'state': state,
            'detail': detail,
            'document_id': doc.pk,
            'url': f'/documents/{doc.pk}/view/',
            'stalled': _stalled(state, doc.uploaded_at),
        })

    # Files the job accepted but has not created a row for yet.
    for index in range(len(files), total):
        files.append({'name': f'File {index + 1}', 'state': 'queued', 'detail': '',
                      'document_id': None, 'url': None,
                      'stalled': _stalled('queued', job.created_at)})

    counts = {'completed': 0, 'processing': 0, 'queued': 0,
              'failed': 0, 'duplicate': 0, 'removed': 0}
    for row in files:
        counts[row['state']] = counts.get(row['state'], 0) + 1

    # A batch is finished when every file has reached a terminal state -- not
    # when the file-saving job says "completed", which was the old mistake.
    settled = (counts['completed'] + counts['failed']
               + counts['duplicate'] + counts['removed'])
    analysing, requested_at = (_analysis_pending(payload) if total and settled >= total
                               else (False, None))
    finished = total > 0 and settled >= total and not analysing
    stalled = any(row.get('stalled') for row in files) or bool(
        analysing and requested_at and timezone.now() - requested_at > STALL_AFTER
    )

    return {
        'job_id': job.pk,
        'status': 'failed' if job.status == 'failed' else ('completed' if finished else 'running'),
        'job_status': job.status,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'total': total,
        'counts': counts,
        'settled': settled,
        'percent': round(settled * 100 / total) if total else 0,
        'finished': finished,
        # Every file is through, and the batch's clustering run is still going.
        'analysing': analysing,
        'stalled': stalled,
        # Worth putting on the upload page at all: still running, or finished
        # recently enough to be news. A batch whose documents have all since
        # been deleted has nothing left to report.
        'is_current': (
            (not finished)
            or (bool(job.created_at)
                and timezone.now() - job.created_at <= KEEP_FINISHED_FOR)
        ) and counts['removed'] < total,
        'files': files,
        'error': job.error or '',
        'job_errors': job_errors,
    }


def recent_batches(user, limit: int = 5) -> list:
    """
    The user's recent upload batches, newest first.

    Superusers still only see their own here: this is the "what did *I* upload"
    panel, not an audit view.
    """
    jobs = (BackgroundJob.objects
            .filter(created_by=user, job_type__in=BATCH_JOB_TYPES)
            # -id as a tiebreak: two batches created in the same instant would
            # otherwise come back in an arbitrary order.
            .order_by('-created_at', '-id')[:limit])
    return [batch_detail(job) for job in jobs]

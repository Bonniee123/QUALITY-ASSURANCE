"""Plain-language messages for in-app notifications (no job IDs or internal jargon)."""


def bulk_upload_notification_message(job, *, success=True) -> str:
    """User-facing text when a bulk upload background job finishes."""
    payload = job.payload or {}
    total = int(payload.get('total_count') or 0)
    processed = int(payload.get('processed_count') or 0)
    error_count = len(payload.get('errors') or [])
    # Near-duplicates are found after upload now, in the background, and are not
    # added. They went through processing, so they come out of the success count
    # and are reported in a sentence of their own.
    duplicate_count = len(payload.get('rejected') or {})
    # The files that went through and were kept, as the job counted them.
    # processed_count is progress and includes the files that failed, which is
    # how a batch with a damaged file was reported as "10 documents uploaded
    # successfully". Jobs from before this was recorded fall back to it.
    succeeded = payload.get('succeeded_count')
    # Clustering and the duplicate review run after the batch, as their own job;
    # until then its documents are in the Repository but not "ready".
    analysing = bool(payload.get('analysis_requested_at'))

    if not success:
        return 'Your upload could not be completed. Please try again or contact the QA office.'

    if not duplicate_count:
        kept = int(succeeded) if succeeded is not None else processed
        return _outcome_message(total, kept, error_count, analysing)

    kept = int(succeeded) if succeeded is not None else max(0, processed - duplicate_count)
    note = (f'{duplicate_count} file matches an existing document and was not added.'
            if duplicate_count == 1 else
            f'{duplicate_count} files match existing documents and were not added.')
    if kept or error_count:
        return f'{_outcome_message(max(0, total - duplicate_count), kept, error_count, analysing)} {note}'
    return note


def _outcome_message(total, processed, error_count, analysing=False) -> str:
    if processed <= 0 and total > 0:
        return 'We could not process your upload. Please check your file(s) and try again.'

    if total == 1 and processed == 1 and error_count == 0:
        if analysing:
            return ('Your document was uploaded successfully and is in the Repository. '
                    'Its duplicate check and clustering will finish shortly.')
        return 'Your document was uploaded successfully and is ready in the Repository.'

    if error_count == 0:
        word = 'document' if processed == 1 else 'documents'
        if analysing:
            return (f'{processed} {word} uploaded successfully and in the Repository. '
                    'Duplicate checks and clustering will finish shortly.')
        return f'{processed} {word} uploaded successfully and ready in the Repository.'

    ok_word = 'document' if processed == 1 else 'documents'
    fail_word = 'file' if error_count == 1 else 'files'
    return (
        f'{processed} {ok_word} uploaded successfully. '
        f'{error_count} {fail_word} could not be processed — open the Repository to review.'
    )


def duplicate_detected_message(doc_title: str, similar_count: int) -> str:
    """When AI finds a file that may match an existing upload."""
    title = (doc_title or 'Your document').strip()[:120]
    if similar_count <= 1:
        return f'"{title}" may be similar to another file already in the Repository.'
    return f'"{title}" may be similar to {similar_count} other files in the Repository.'


def version_supersede_message(new_title: str, old_title: str) -> str:
    """When QA Head marks one document as replacing an older one."""
    new_t = (new_title or 'A document').strip()[:100]
    old_t = (old_title or 'an older document').strip()[:100]
    return f'"{new_t}" was set as a newer version of "{old_t}".'


def message_arrived_message(sender_name: str, unread_count: int = 1, has_text: bool = True) -> str:
    """
    A notification about a direct message: who wrote, never what they wrote.

    The bell used to carry the first ninety characters of the message body, so
    a conversation could be read out of the notification list, and a handful of
    messages made that list several screens long. The words belong in Messages,
    which is where the notification links to.
    """
    name = (sender_name or 'Someone').strip() or 'Someone'
    if unread_count and unread_count > 1:
        return f'{name} sent you {unread_count} messages.'
    if not has_text:
        return f'{name} shared a document with you.'
    return f'{name} sent you a message.'


def display_notification_message(raw: str) -> str:
    """Plain-language display text for stored notifications (cleans legacy job-ID copy)."""
    import re

    if not raw:
        return raw
    msg = raw.strip()
    if re.search(r'job\s*#\d+', msg, re.I):
        msg = re.sub(r'\s*\(?job\s*#\d+\)?\.?', '', msg, flags=re.I).strip()
        msg = re.sub(
            r'^\d+/\d+\s+document\(s\)\s+processed\.?\s*',
            '',
            msg,
            flags=re.I,
        ).strip()
        msg = re.sub(
            r'(?:AI processing|Document analysis) (completed|queued)[^.]*\.?\s*',
            '',
            msg,
            flags=re.I,
        ).strip()
        if not msg or re.match(r'^(?:AI processing|Document analysis)', msg, re.I):
            return 'Your documents were processed. Open the Repository to review.'
    return msg or raw

"""Background job enqueue + execution helpers for heavy processing tasks."""
import logging
import os
import threading
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import BackgroundJob, Document, ProcessingMetric, ActivityLog
from .text_extraction import explain_extraction, extract_text, is_damaged_file_problem
from .ai_pipeline import run_full_ai_pipeline, run_light_post_upload

logger = logging.getLogger(__name__)


def enqueue_job(job_type, payload=None, created_by=None, inline=None):
    job = BackgroundJob.objects.create(
        job_type=job_type,
        payload=payload or {},
        created_by=created_by,
    )
    if inline is None:
        should_run_inline = bool(getattr(settings, 'AI_RUN_JOBS_INLINE', True))
    else:
        should_run_inline = bool(inline)
    if should_run_inline:
        run_job(job)
        job.refresh_from_db()
    else:
        _dispatch_job_async(job)
    return job


def _run_job_in_thread(job):
    """
    Thread entry point for asynchronous jobs.

    Anything raised here would otherwise die inside the worker thread: the job row
    would sit at 'pending' forever and nothing would surface in the UI. Catch
    everything and record it on the job instead.
    """
    from django.db import connection

    try:
        run_job(job)
    except Exception:
        logger.exception('Background job %s (%s) crashed in worker thread', job.pk, job.job_type)
        _mark_job_crashed(job)
    finally:
        # Django opens a connection per thread and never closes it for us, so a
        # worker has to release its own before exiting. Only close a connection this
        # thread owns: on the main thread it belongs to the caller, and closing it
        # aborts whatever transaction the caller is inside.
        if threading.current_thread() is not threading.main_thread():
            connection.close()


def _dispatch_job_async(job):
    # Named so a management command can wait for it. Without a name there is
    # no way to tell a job worker apart from any other thread in the process,
    # and a command that exits while one is running kills it mid-job.
    threading.Thread(target=_run_job_in_thread, args=(job,), daemon=True,
                     name=f'qa-job-{job.pk}').start()


def _mark_job_crashed(job):
    """Best-effort: move a job out of 'pending'/'running' after an unexpected crash."""
    try:
        BackgroundJob.objects.filter(pk=job.pk).update(
            status='failed',
            error='Job crashed unexpectedly. See server logs for the traceback.',
            finished_at=timezone.now(),
        )
    except Exception:
        logger.exception('Could not mark background job %s as failed', job.pk)


def recover_interrupted_jobs():
    """
    Queue again the jobs a previous server process was running when it stopped.

    Jobs run on threads inside the web server, so a restart kills them mid-way and
    the row used to stay 'running' for ever: the batch never finished, its files
    sat in "Processing..." and the progress pill kept spinning. This runs at
    start-up, when nothing can still be running them. Every job type is safe to
    run again: extraction skips files that already have text, and the pipeline
    recomputes what it writes.
    """
    stale = BackgroundJob.objects.filter(status='running')
    count = stale.count()
    if count:
        stale.update(status='pending', started_at=None)
        logger.warning('Re-queued %s background job(s) interrupted by a server restart.', count)
    return count


def sweep_stale_jobs(minutes=None):
    """
    Fail jobs whose worker stopped without saying so, and free their documents.

    `recover_interrupted_jobs` handles the case where the whole process died and
    came back: it runs at start-up, when nothing can still be working. This
    handles the other case, where the process is alive and well but the thread
    doing the work is gone -- a native crash inside an embedding or OCR library
    takes the thread with it and raises nothing Python can catch. The job row
    then says 'running' for ever, and every document in the batch keeps saying
    "Processing" on a page that will never change.

    Staleness is measured from the last progress report, so a slow job that is
    genuinely working is never cut off. Documents left with no text are given a
    processing_error, because that is what stops the spinner: a document with
    no text, no error and is_processed False is, by definition, still in
    progress. An error a person can read and retry beats a spinner that lies.
    """
    minutes = getattr(settings, 'JOB_STALE_MINUTES', 20) if minutes is None else minutes
    if not minutes or minutes <= 0:
        return 0

    cutoff = timezone.now() - timedelta(minutes=minutes)
    swept = 0
    for job in BackgroundJob.objects.filter(status='running'):
        if _last_sign_of_life(job) > cutoff:
            continue
        BackgroundJob.objects.filter(pk=job.pk, status='running').update(
            status='failed',
            finished_at=timezone.now(),
            error=(f'Stopped responding for over {minutes} minutes and was marked failed. '
                   f'Run it again from Document Analysis, or re-upload the files that '
                   f'did not finish.'),
        )
        _release_unfinished_documents(job)
        swept += 1
        logger.warning('Job %s (%s) stopped reporting progress; marked failed.', job.pk, job.job_type)
    return swept


def _last_sign_of_life(job):
    """The most recent moment this job proved it was still working."""
    beat = (job.payload or {}).get('heartbeat')
    if beat:
        parsed = parse_datetime(beat)
        if parsed is not None:
            return parsed
    return job.started_at or job.created_at


def _release_unfinished_documents(job):
    """Take the documents of a dead job off "Processing"."""
    doc_ids = list((job.payload or {}).get('document_ids') or [])
    if not doc_ids:
        return
    Document.objects.filter(pk__in=doc_ids, is_processed=False).update(
        processing_error='Processing stopped before this file was finished. '
                         'Upload it again to retry.',
    )


def resume_pending_jobs(limit=50):
    """Run any jobs left in pending state, and those a restart interrupted."""
    recover_interrupted_jobs()
    pending = list(
        BackgroundJob.objects.filter(status='pending').order_by('created_at')[:limit]
    )
    for job in pending:
        run_job(job)
    return len(pending)


def _persist_job_state(job, **fields):
    """
    Write job state without raising when the row is not visible to this connection.

    `Model.save(update_fields=...)` raises DatabaseError('Save with update_fields did
    not affect any rows') if the row is missing — which happens when a worker thread
    starts before the enqueueing transaction has committed. A queryset update simply
    matches zero rows instead, so a bookkeeping write can never take down the job.
    """
    for name, value in fields.items():
        setattr(job, name, value)
    try:
        BackgroundJob.objects.filter(pk=job.pk).update(**fields)
    except Exception:
        logger.exception('Could not persist state %s for background job %s', list(fields), job.pk)


def run_job(job):
    started = timezone.now()
    _persist_job_state(job, status='running', started_at=started, error='')
    try:
        if job.job_type == 'full_ai_pipeline':
            result = run_full_ai_pipeline(None)
        elif job.job_type == 'light_post_upload':
            ids = list((job.payload or {}).get('document_ids') or [])
            docs = list(Document.objects.filter(pk__in=ids))
            result = run_light_post_upload(None, docs)
        elif job.job_type == 'bulk_upload_process':
            result = _run_bulk_upload_process(job)
        elif job.job_type == 'refresh_duplicate_flags':
            result = _refresh_duplicate_flags()
        elif job.job_type == 'reprocess_ocr':
            result = _reprocess_ocr(job.payload or {}, created_by=job.created_by, refresh_after=True)
        elif job.job_type == 'reindex_search_artifacts':
            result = _reindex_search_artifacts()
        else:
            raise ValueError(f'Unknown job_type: {job.job_type}')
        _persist_job_state(
            job, status='completed', result=str(result), finished_at=timezone.now()
        )
        if job.job_type == 'bulk_upload_process':
            _notify_bulk_job_finished(job, success=True)
        _record_metric('background_job_duration_ms', (job.finished_at - started).total_seconds() * 1000, meta={'job_type': job.job_type, 'status': 'completed'})
        return True
    except Exception as exc:
        logger.exception('Background job %s (%s) failed', job.pk, job.job_type)
        _persist_job_state(
            job, status='failed', error=str(exc), finished_at=timezone.now()
        )
        if job.job_type == 'bulk_upload_process':
            _notify_bulk_job_finished(job, success=False)
        _record_metric('background_job_duration_ms', (job.finished_at - started).total_seconds() * 1000, meta={'job_type': job.job_type, 'status': 'failed'})
        return False


def _update_job_payload(job, **fields):
    payload = dict(job.payload or {})
    payload.update(fields)
    # Every progress report is also a heartbeat. Without one the only
    # timestamp on a running job is when it started, and a job that is making
    # slow but real progress through big scanned files would be
    # indistinguishable from one whose thread died.
    payload['heartbeat'] = timezone.now().isoformat()
    _persist_job_state(job, payload=payload)


def _is_ocr_method(method):
    return method in ('ocr_extraction', 'pdf_ocr_fallback')


def _store_image_phash(doc):
    """Compute and persist the perceptual hash for image documents (best-effort)."""
    try:
        from ai_processing.image_hash import is_image_file, compute_image_hash
        if not is_image_file(doc.file_type):
            return
        if doc.image_phash:
            # Hashed at upload time already: the upload request needs the hash
            # for its visual-duplicate check and stores it on the document.
            return
        if not doc.file or not hasattr(doc.file, 'path') or not os.path.exists(doc.file.path):
            return
        phash = compute_image_hash(doc.file.path)
        if phash and phash != doc.image_phash:
            doc.image_phash = phash
            doc.save(update_fields=['image_phash'])
    except Exception as exc:  # noqa: BLE001 - never block processing on hashing
        logger.info('Image phash store skipped for doc %s: %s', getattr(doc, 'pk', '?'), exc)


# One batch is processed at a time. A second batch waits here rather than
# running alongside: its near-duplicate check has to see the text of the batch
# before it, and two batches at once would also double the Tesseract processes
# competing for the same cores.
_INGEST_LOCK = threading.Lock()


def _extraction_workers(count):
    """How many files to extract at once."""
    configured = getattr(settings, 'UPLOAD_EXTRACTION_WORKERS', None)
    if configured:
        return max(1, min(int(configured), count or 1))
    # Measured on a 12-core machine: 4 workers extract 3.8x faster than 1, and
    # 6 or 8 add almost nothing. Half the cores, capped at 4, leaves the rest
    # to the web server.
    return max(1, min(4, (os.cpu_count() or 2) // 2, count or 1))


def _extract_for_upload(path):
    """
    Text for one saved upload. Runs on a worker thread, so it touches no
    database -- Django connections are per thread, and every write stays on the
    thread that owns the batch.
    """
    try:
        text, method = extract_text(path)
    except Exception as exc:  # re-raised on the batch thread, per document
        return '', 'error', exc, '', ''
    try:
        problem, notice = explain_extraction(path, text, method)
    except Exception:  # the explanation is a courtesy; it never fails the file
        problem, notice = '', ''
    return text, method, None, problem, notice


def _near_duplicate_of(doc, text, later_ids):
    """
    A stored document this upload's text duplicates, or (None, 0.0).

    This is the check the upload request used to run before saving. It now runs
    here, after extraction, against the same set: every stored document of the
    same type, plus the files ahead of this one in its own batch -- never the
    ones behind it, which the request would not have seen yet either. Stored
    text only: nothing is re-read or re-OCR'd to answer it.
    """
    from .near_duplicates import find_near_duplicate, same_format_types

    if not (text or '').strip():
        return None, 0.0
    candidates = (
        Document.objects.live()
        .filter(file_type__in=same_format_types(doc.file_type), is_archived=False)
        .exclude(pk=doc.pk)
        .exclude(pk__in=list(later_ids))
        .only('title', 'extracted_text', 'ocr_text')
        .iterator()
    )
    return find_near_duplicate(text, candidates, lambda d: d.combined_text)


def _discard_rejected_upload(doc):
    """Remove an upload that turned out to duplicate an existing document."""
    try:
        if doc.file:
            doc.file.delete(save=False)
    except Exception as exc:  # noqa: BLE001 - the row still has to go
        logger.info('Could not delete file for rejected upload %s: %s', doc.pk, exc)
    deleted_pk = doc.pk
    doc.delete()
    from .ai_pipeline import forget_deleted_matches
    forget_deleted_matches([deleted_pk])


def _run_bulk_upload_process(job):
    with _INGEST_LOCK:
        return _process_upload_batch(job)


def _process_upload_batch(job):
    from concurrent.futures import ThreadPoolExecutor

    from .auto_metadata import extract_metadata_from_text, extract_metadata_from_filename

    payload = job.payload or {}
    doc_ids = list(payload.get('document_ids') or [])
    total_count = len(doc_ids)
    errors = []
    rejected = dict(payload.get('rejected') or {})
    processed_docs = []

    _update_job_payload(job, total_count=total_count, processed_count=0, errors=[])

    # Extraction -- OCR for images and scanned PDFs -- is the slow step, and it
    # is independent per file, so it runs on a small pool while this thread
    # takes the results in upload order and does every database write itself.
    to_extract = {}
    for doc in Document.objects.filter(pk__in=doc_ids).only('file', 'extracted_text', 'ocr_text'):
        if (doc.combined_text or '').strip():
            continue  # already extracted (e.g. by a pre-save check) -- reuse it
        try:
            path = doc.file.path if doc.file else ''
        except Exception:
            path = ''
        if path and os.path.exists(path):
            to_extract[doc.pk] = path

    with ThreadPoolExecutor(max_workers=_extraction_workers(len(to_extract)),
                            thread_name_prefix='qa-extract') as pool:
        pending = {pk: pool.submit(_extract_for_upload, path) for pk, path in to_extract.items()}

        for idx, doc_id in enumerate(doc_ids):
            filename = f'document-{doc_id}'
            try:
                doc = Document.objects.get(pk=doc_id)
                filename = os.path.basename(doc.file.name) if doc.file else filename
                if not doc.file or not hasattr(doc.file, 'path') or not os.path.exists(doc.file.path):
                    raise ValueError('File missing on disk')

                if doc_id in pending:
                    result = pending[doc_id].result()
                    extracted, method, failure = result[:3]
                    problem, notice = (tuple(result[3:5]) + ('', ''))[:2]
                    if failure is not None:
                        raise failure
                    if extracted:
                        # `notice` says what OCR left out of a scanned PDF (pages
                        # past the limit, or a file too large to OCR at all).
                        if _is_ocr_method(method):
                            doc.ocr_text = extracted
                            doc.ocr_status = 'success'
                            doc.ocr_error = notice
                            doc.save(update_fields=['ocr_text', 'ocr_status', 'ocr_error'])
                        else:
                            doc.extracted_text = extracted
                            doc.ocr_error = notice or doc.ocr_error
                            doc.save(update_fields=['extracted_text', 'ocr_error'])
                    elif is_damaged_file_problem(problem):
                        # A damaged file is a failed upload, not an empty document:
                        # it used to be stored as processed, with no error, and
                        # counted as a success.
                        raise ValueError(problem)
                    elif method in ('ocr_failed', 'pdf_extraction') or problem:
                        doc.ocr_status = 'failed'
                        doc.ocr_error = problem or notice or 'OCR/extraction produced no text.'
                        doc.save(update_fields=['ocr_status', 'ocr_error'])
                else:
                    extracted = (doc.combined_text or '').strip()

                _store_image_phash(doc)

                match, ratio = _near_duplicate_of(doc, extracted, doc_ids[idx + 1:])
                if match is not None:
                    # The match is named only if the uploader may open it (a
                    # Faculty member was shown titles from other areas here).
                    from accounts.permissions import user_can_access_document
                    from .near_duplicates import as_percent, blocked_message, document_label

                    visible = job.created_by is None or user_can_access_document(job.created_by, match)
                    match_name = (document_label(match.title) if visible
                                  else 'a document already in the archive')
                    reason = blocked_message(match_name, as_percent(ratio))
                    rejected[str(doc_id)] = {'name': filename, 'reason': reason,
                                             'match_id': match.pk if visible else None}
                    _discard_rejected_upload(doc)
                    _update_job_payload(job, processed_count=idx + 1, errors=errors,
                                        rejected=rejected)
                    continue

                meta = extract_metadata_from_text(extracted, filename) if extracted else extract_metadata_from_filename(filename)

                if meta.get('title'):
                    doc.title = meta['title']
                if meta.get('year'):
                    try:
                        doc.year = int(meta['year'])
                    except (ValueError, TypeError):
                        pass
                if meta.get('document_type'):
                    doc.document_type = meta['document_type']
                if meta.get('qa_area') and not (doc.qa_area or '').strip():
                    doc.qa_area = meta['qa_area']
                    # Link the area itself, not just its code in text: Faculty
                    # scoping, Area Submissions and the area filter follow acc_area.
                    if doc.acc_area_id is None:
                        from qa_structure.models import AccreditationArea
                        doc.acc_area = AccreditationArea.objects.filter(area_code=meta['qa_area']).first()
                if meta.get('criterion'):
                    doc.criterion = meta['criterion']
                if meta.get('indicator'):
                    doc.indicator = meta['indicator']
                if meta.get('description'):
                    doc.description = meta['description']

                doc.processing_error = ''
                doc.is_processed = True
                doc.save()
                processed_docs.append(doc)

                if job.created_by_id:
                    ActivityLog.objects.create(
                        user_id=job.created_by_id,
                        action='bulk_upload',
                        description=f'Bulk uploaded: {doc.title} ({doc.file_type}) — metadata auto-extracted',
                    )
            except Exception as exc:
                logger.error('Bulk upload process error for %s: %s', filename, exc)
                errors.append(f'{filename}: {exc}')
                try:
                    doc = Document.objects.filter(pk=doc_id).first()
                    if doc:
                        doc.processing_error = str(exc)
                        doc.save(update_fields=['processing_error'])
                except Exception:
                    pass

            _update_job_payload(job, processed_count=idx + 1, errors=errors)

    _update_job_payload(job, succeeded_count=len(processed_docs))
    ai_result = ''
    if processed_docs:
        try:
            if bool(getattr(settings, 'AI_USE_BACKGROUND_JOBS', True)):
                # Clustering and duplicate review run once for the whole batch,
                # after every file's text is in -- never once per file. The
                # timestamp lets the upload page tell when the run that covers
                # this batch has finished.
                _update_job_payload(job, analysis_requested_at=timezone.now().isoformat())
                request_full_pipeline(job.created_by)
                ai_result = 'Document analysis is running in the background.'
            else:
                ai_result = run_full_ai_pipeline(None)

            if job.created_by_id:
                ActivityLog.objects.create(
                    user_id=job.created_by_id,
                    action='auto_ai_processing',
                    description=f'Automatic analysis after bulk upload ({len(processed_docs)} files): {ai_result}',
                )
        except Exception as exc:
            logger.error('AI pipeline error after bulk upload job #%s: %s', job.pk, exc)
            ai_result = 'Document analysis will run later.'

    msg = f'{len(processed_docs)}/{total_count} document(s) processed.'
    if rejected:
        msg += f' {len(rejected)} duplicate file(s) not added.'
    if errors:
        msg += f' {len(errors)} file(s) failed.'
    if ai_result:
        msg += f' {ai_result}'
    return msg


# ------------------------------------------------------------------------
# Full-pipeline runs, coalesced.
#
# Every batch used to start its own full run over the whole corpus, each on its
# own thread, so batches uploaded back to back meant several runs clustering
# the same documents at once and racing to write the labels. A run reads every
# document when it starts, so one run that starts *after* a batch covers it --
# and any number of batches that finish while a run is going can share the one
# run that follows.
# ------------------------------------------------------------------------
_PIPELINE_STATE = threading.Lock()
_pipeline_running = False
_pipeline_dirty = False


def request_full_pipeline(created_by=None):
    """
    Ensure a full pipeline run starts after this call.

    At most one run is in progress at a time. Requests that arrive during a run
    are folded into exactly one follow-up run, however many there are. Returns
    True when this call started the worker, False when it was folded in.
    """
    global _pipeline_running, _pipeline_dirty
    with _PIPELINE_STATE:
        if _pipeline_running:
            _pipeline_dirty = True
            return False
        _pipeline_running = True
    created_by_id = getattr(created_by, 'pk', created_by)
    threading.Thread(target=_pipeline_worker, args=(created_by_id,),
                     daemon=True, name='qa-pipeline').start()
    return True


def _pipeline_worker(created_by_id):
    global _pipeline_running, _pipeline_dirty
    from django.db import connection

    finished_cleanly = False
    try:
        while True:
            with _PIPELINE_STATE:
                # Cleared before the run reads anything, so a request arriving
                # from here on gets a run of its own afterwards.
                _pipeline_dirty = False
            job = BackgroundJob.objects.create(
                job_type='full_ai_pipeline', payload={}, created_by_id=created_by_id,
            )
            try:
                run_job(job)
            except Exception:
                logger.exception('Coalesced pipeline run %s crashed', job.pk)
                _mark_job_crashed(job)
            with _PIPELINE_STATE:
                if not _pipeline_dirty:
                    _pipeline_running = False
                    finished_cleanly = True
                    return
    finally:
        if not finished_cleanly:
            # Only an unexpected exit resets the flag here. After a clean exit a
            # new worker may already own it, and clearing it again would let a
            # second worker start alongside that one.
            with _PIPELINE_STATE:
                _pipeline_running = False
        connection.close()


def _notify_bulk_job_finished(job, success=True):
    user = job.created_by
    if not user:
        return
    try:
        from notifications.services import notify
        from notifications.user_messages import bulk_upload_notification_message

        message = bulk_upload_notification_message(job, success=success)
        category = 'upload' if success else 'system'
        notify(user, message, category=category, link=reverse('documents:repository'))
    except Exception as exc:
        logger.error('Failed to notify bulk job completion for job #%s: %s', job.pk, exc)


def serialize_job(job):
    payload = job.payload or {}
    filenames = list(payload.get('filenames') or [])
    if not filenames:
        doc_ids = list(payload.get('document_ids') or [])
        if doc_ids:
            id_order = {pk: idx for idx, pk in enumerate(doc_ids)}
            docs = Document.objects.filter(pk__in=doc_ids)
            docs = sorted(docs, key=lambda d: id_order.get(d.pk, len(doc_ids)))
            for doc in docs:
                if doc.file:
                    filenames.append(os.path.basename(doc.file.name))
                else:
                    filenames.append(doc.title)
    return {
        'id': job.pk,
        'job_type': job.job_type,
        'status': job.status,
        'result': job.result,
        'error': job.error,
        'processed_count': payload.get('processed_count', 0),
        'total_count': payload.get('total_count', 0),
        'filenames': filenames,
        'errors': payload.get('errors', []),
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
    }


def _refresh_duplicate_flags():
    docs = list(Document.objects.live().filter(is_archived=False))
    if not docs:
        return 'No documents to refresh.'
    from ai_processing.tfidf_service import compute_tfidf_keywords
    from ai_processing.duplicate_checker import check_all_duplicates
    from ai_processing.image_hash import is_image_file
    from .ai_pipeline import (
        _duplicate_snapshot, _visual_matches, settle_duplicate_verdict, verified_text_matches,
    )
    tfidf_matrix, _feature_names, _keywords = compute_tfidf_keywords([d.combined_text or d.title for d in docs])
    if tfidf_matrix is None:
        return 'TF-IDF unavailable for duplicate refresh.'
    dup_map = check_all_duplicates(tfidf_matrix)

    # The same rules as the full run, so the two never disagree: text decides
    # only where the text is the document, images are judged by their pixels
    # (with the name-corroborated review band), and staff decisions are kept.
    min_text = int(getattr(settings, 'DUPLICATE_TEXT_MIN_CHARS', 400))
    before = _duplicate_snapshot(docs)
    visual_map = _visual_matches(docs)
    frequencies = {}

    changed = 0
    for idx, doc in enumerate(docs):
        trust_text = (not is_image_file(doc.file_type)
                      and len((doc.combined_text or '').strip()) >= min_text)
        dups = dup_map.get(idx, []) if trust_text else []
        similar = verified_text_matches(doc, dups, docs, frequencies)
        existing_ids = {m['id'] for m in similar}
        for vm in visual_map.get(doc.pk, []):
            if vm['id'] not in existing_ids:
                similar.append(vm)
                existing_ids.add(vm['id'])
        similar.sort(key=lambda x: x.get('similarity', 0), reverse=True)
        was = (doc.duplicate_status, doc.similar_documents)
        settle_duplicate_verdict(doc, similar, *before[doc.pk])
        if (doc.duplicate_status, doc.similar_documents) != was:
            changed += 1
    return f'Duplicate flags refreshed for {len(docs)} documents ({changed} changed).'


def _reprocess_ocr(payload, created_by=None, refresh_after=False):
    only_empty = bool(payload.get('only_empty', True))
    pdf_only = bool(payload.get('pdf_only', True))
    ids = list(payload.get('document_ids') or [])
    qs = Document.objects.live().filter(is_archived=False)
    if ids:
        qs = qs.filter(pk__in=ids)
    if pdf_only:
        qs = qs.filter(file_type='pdf')
    if only_empty:
        qs = qs.filter(ocr_text='')
    processed = 0
    new_text = 0
    for doc in qs:
        if not doc.file or not hasattr(doc.file, 'path'):
            continue
        doc.ocr_status = 'retrying'
        doc.save(update_fields=['ocr_status'])
        text, method = extract_text(doc.file.path)
        try:
            problem, notice = explain_extraction(doc.file.path, text, method)
        except Exception:
            problem, notice = '', ''
        if text and method in ('ocr_extraction', 'pdf_ocr_fallback'):
            new_text += text != doc.ocr_text
            doc.ocr_text = text
            doc.ocr_status = 'success'
            doc.ocr_error = notice
            doc.save(update_fields=['ocr_text', 'ocr_status', 'ocr_error'])
        elif text:
            # A Word or Excel file, or a PDF with a text layer: its text is read
            # directly and OCR does not apply. It used to be marked "OCR failed".
            new_text += text != doc.extracted_text
            doc.extracted_text = text
            doc.ocr_status = 'not_run'
            doc.ocr_error = notice
            doc.save(update_fields=['extracted_text', 'ocr_status', 'ocr_error'])
        else:
            doc.ocr_status = 'failed'
            doc.ocr_error = problem or notice or 'OCR text not extracted during retry.'
            doc.save(update_fields=['ocr_status', 'ocr_error'])
        processed += 1
    if new_text and refresh_after:
        # New text changes the keywords, clusters and duplicate matches, which
        # were left as they were: one pipeline run brings them up to date. (Only
        # from the server's job runner; the management command would exit under it.)
        request_full_pipeline(created_by)
    return f'OCR retry processed {processed} documents.'


def _reindex_search_artifacts():
    docs = list(Document.objects.live().filter(is_archived=False))
    if not docs:
        return 'No documents to reindex.'
    from ai_processing.tfidf_service import compute_tfidf_keywords
    tfidf_matrix, _feature_names, keywords_per_doc = compute_tfidf_keywords([d.combined_text or d.title for d in docs])
    if tfidf_matrix is None:
        return 'Reindex failed: TF-IDF matrix unavailable.'
    for i, doc in enumerate(docs):
        if i < len(keywords_per_doc):
            doc.tfidf_keywords = keywords_per_doc[i]
            doc.save(update_fields=['tfidf_keywords'])
    return f'Reindexed TF-IDF artifacts for {len(docs)} documents.'


def _record_metric(name, value, unit='ms', meta=None):
    ProcessingMetric.objects.create(
        metric_name=name,
        metric_value=float(value),
        unit=unit,
        meta=meta or {},
    )

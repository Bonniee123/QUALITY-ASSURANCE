"""
Views for document upload, repository listing, detail, and management.
"""
import os
import logging
import hashlib
import tempfile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import content_disposition_header
from django.conf import settings
from django.views.decorators.clickjacking import xframe_options_sameorigin
from .jobs import enqueue_job, serialize_job
from .models import Document, ActivityLog, BackgroundJob
from .forms import (
    DocumentUploadForm, DocumentEditForm, StructuredDocumentUploadForm,
    FacultyUploadForm,
)
from .text_extraction import extract_text
from .upload_validation import upload_content_problem
from accounts.decorators import (
    role_required, qa_staff_required, repository_access_required, faculty_required,
)
from accounts.permissions import (
    is_faculty, scope_documents_for_user, faculty_area_scope, faculty_assigned_area_codes,
    user_can_access_document, user_can_modify_document, NO_AREA_SENTINEL,
)
from qa_archiving_system import rate_limit

logger = logging.getLogger(__name__)

# The duplicate states that mean "a person still has to look at this".
# Same tuple the Dashboard and AI Processing count with, so the three
# pages cannot disagree about what needs review.
DUPLICATE_REVIEW_STATUSES = ('possible', 'pending_check', 'confirmed_dup')


def _bulk_upload_max_files():
    return int(getattr(settings, 'BULK_UPLOAD_MAX_FILES', 100))


def _run_ai_pipeline(request):
    """Run the full AI pipeline on all documents (delegates to ai_pipeline module)."""
    from .ai_pipeline import run_full_ai_pipeline

    return run_full_ai_pipeline(request)


def _is_ocr_method(method):
    return method in ('ocr_extraction', 'pdf_ocr_fallback')


def _sha256_uploaded_file(uploaded_file):
    hasher = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        hasher.update(chunk)
    uploaded_file.seek(0)
    return hasher.hexdigest()


def _is_exact_duplicate_upload(uploaded_file, file_ext, uploaded_hash=None):
    """
    True when a byte-identical file is already archived.

    Compares SHA-256 against the indexed Document.content_sha256 column — one query
    rather than re-hashing every stored file of this type on every upload. Rows that
    have no hash yet (uploaded before the column existed) are backfilled on demand,
    so the fallback scan shrinks to nothing after the first pass.
    """
    from .near_duplicates import same_format_types

    file_type_cleaned = (file_ext or '').lstrip('.').lower()
    if not file_type_cleaned:
        return False

    if not uploaded_hash:
        uploaded_hash = _sha256_uploaded_file(uploaded_file)

    if Document.objects.filter(
        file_type__in=same_format_types(file_type_cleaned),
        is_archived=False,
        content_sha256=uploaded_hash,
    ).exists():
        return True

    # Legacy rows with no stored hash: hash them once, then compare.
    unhashed = Document.objects.filter(
        file_type__in=same_format_types(file_type_cleaned),
        is_archived=False,
        content_sha256='',
    )
    for pdup in unhashed.iterator():
        if pdup.ensure_content_hash() == uploaded_hash:
            return True
    return False


def _extract_uploaded_text_for_duplicate_check(uploaded_file):
    """
    Extract text from an uploaded file before saving so we can detect near-duplicates.
    Returns empty string when extraction is not possible.
    """
    suffix = os.path.splitext(uploaded_file.name or '')[1].lower() or '.tmp'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        extracted, _method = extract_text(tmp_path)
        return (extracted or '').strip()
    except Exception:
        return ''
    finally:
        uploaded_file.seek(0)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _backfill_document_text(doc) -> str:
    """
    Text for a stored document, extracting it from disk if it has none yet.

    Returns '' when the file is missing or cannot be read; the caller then skips
    the candidate exactly as before. The extracted text is saved so the work is
    done once per document rather than on every subsequent upload.
    """
    try:
        path = doc.file.path
    except Exception:
        return ''
    if not path or not os.path.exists(path):
        return ''
    try:
        extracted, method = extract_text(path)
    except Exception:
        return ''
    extracted = (extracted or '').strip()
    if not extracted:
        return ''
    # Stored in the field the background job would have used, so the job reuses
    # it rather than extracting a second time -- and an image no longer ends up
    # with the same OCR text in both fields, which doubled every word in it.
    if _is_ocr_method(method):
        fields = {'ocr_text': extracted, 'ocr_status': 'success', 'ocr_error': ''}
    else:
        fields = {'extracted_text': extracted}
    try:
        # `potential_dups` defers most columns, so refetch before writing rather
        # than saving a partially-loaded instance.
        Document.objects.filter(pk=doc.pk).update(**fields)
    except Exception:
        pass
    return extracted


def _awaiting_extraction(doc) -> bool:
    """True while a stored document's own text extraction has not run yet."""
    return not doc.is_processed and not (doc.processing_error or '').strip()


def _is_near_duplicate_upload(uploaded_file, file_ext):
    """
    Detect near-duplicate uploads by text similarity.
    Uses SequenceMatcher ratio against existing non-archived documents of same file type.
    """
    from .near_duplicates import find_near_duplicate, min_text_chars, same_format_types

    file_type_cleaned = (file_ext or '').lstrip('.').lower()
    if not file_type_cleaned:
        return False

    candidate_text = _extract_uploaded_text_for_duplicate_check(uploaded_file)
    floor = min_text_chars()
    if len(candidate_text) < floor:
        return False

    def stored_text(doc):
        text = (doc.combined_text or '').strip()
        if len(text) >= floor or not _awaiting_extraction(doc):
            # A document that has already been through extraction keeps the text
            # it has. Reading its file again -- OCR, for an image -- produced
            # nothing new, and it ran for every same-type upload, forever: a
            # photo with no words in it was OCR'd once more for each of them.
            return text
        # No stored text because extraction has not reached this document yet.
        # Skipping it is what let identical files into the archive: extraction
        # runs in a background job, so a document uploaded moments earlier
        # still has an empty `extracted_text` and was silently passed over. Two
        # 90,000-character revisions uploaded 17 seconds apart were
        # byte-different but textually identical, and neither the hash check nor
        # this one saw it.
        #
        # Read the file instead, and keep the result -- the same
        # extract-once-then-compare approach the exact-hash check above uses
        # for rows with no stored hash.
        return _backfill_document_text(doc)

    potential_dups = (
        Document.objects
        .filter(file_type__in=same_format_types(file_type_cleaned), is_archived=False)
        .only('extracted_text', 'ocr_text', 'file', 'is_processed', 'processing_error')
        .iterator()
    )
    match, _ratio = find_near_duplicate(candidate_text, potential_dups, stored_text)
    return match is not None


def _compute_uploaded_image_hash(uploaded_file):
    """Write an uploaded image to a temp file and return its perceptual hash ('' on failure)."""
    from ai_processing.image_hash import compute_image_hash

    suffix = os.path.splitext(uploaded_file.name or '')[1].lower() or '.img'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        return compute_image_hash(tmp_path)
    except Exception:
        return ''
    finally:
        uploaded_file.seek(0)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _visual_duplicate_match(uploaded_file, file_ext, candidate=None, exclude_ids=()):
    """
    An archived image this upload is a copy of, as ``(document, share_pct)``.

    The perceptual hash finds candidates; the pixels decide. The hash alone
    refused honest uploads: on this archive it put a deployment diagram and a
    system-architecture diagram 6 bits apart and called that "91% similar", so
    a new figure drawn in the house style could not be filed. A candidate is now
    opened and compared pixel for pixel, and only a genuine copy is refused --
    anything merely close is saved and flagged for review instead.
    """
    from ai_processing.image_hash import (
        VERDICT_DUPLICATE, compare_matrices, hamming_distance, is_image_file,
        load_image_matrix, max_distance, pixel_verdict,
    )

    if not is_image_file(file_ext):
        return None, 0
    if candidate is None:
        candidate = _compute_uploaded_image_hash(uploaded_file)
    if not candidate:
        return None, 0

    cutoff = max_distance()
    stored = Document.objects.filter(is_archived=False).exclude(image_phash='')
    if exclude_ids:
        stored = stored.exclude(pk__in=list(exclude_ids))
    near = [doc for doc in stored
            if (lambda d: d is not None and d <= cutoff)(hamming_distance(candidate, doc.image_phash))]
    if not near:
        return None, 0

    uploaded_matrix = _uploaded_image_matrix(uploaded_file)
    if uploaded_matrix is None:
        # Cannot read what was just uploaded: do not refuse on the hash alone.
        return None, 0

    best_doc, best_share = None, 0.0
    for doc in near:
        try:
            stored_matrix = load_image_matrix(doc.file.path)
        except (ValueError, OSError):
            continue
        share, mean = compare_matrices(uploaded_matrix, stored_matrix)
        if pixel_verdict(mean) != VERDICT_DUPLICATE:
            continue
        if share is not None and share > best_share:
            best_doc, best_share = doc, share
    return best_doc, round(best_share * 100)


def _uploaded_image_matrix(uploaded_file):
    """The greyscale square of an upload still in memory, for pixel comparison."""
    from ai_processing.image_hash import load_image_matrix

    suffix = os.path.splitext(uploaded_file.name or '')[1].lower() or '.img'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        return load_image_matrix(tmp_path)
    except Exception:  # noqa: BLE001 - comparison is best-effort
        return None
    finally:
        uploaded_file.seek(0)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _wants_json_response(request):
    accept = request.headers.get('Accept', '')
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in accept
    )


def _job_owned_by_user(job, user):
    return job.created_by_id is not None and job.created_by_id == user.id


def _cluster_names():
    from ai_processing.dashboard_utils import cluster_label_map
    return cluster_label_map()


def matched_document_label(user, doc):
    """
    How a duplicate message names the matched document to this uploader.

    The title is shown only when the uploader may open that document: a Faculty
    member's refused upload used to be told the title of a match in another area.
    """
    if doc is not None and user_can_access_document(user, doc):
        return f'"{doc.title}"'
    return 'a document already in the archive'


@login_required
@repository_access_required
def bulk_upload(request):
    """
    Handle bulk drag-and-drop file upload.
    Saves files quickly and queues background processing for extraction, metadata, and AI.
    Faculty uploads are tagged to one of their assigned accreditation areas.
    """
    if request.method == 'POST':
        if not rate_limit.allow(request, 'upload'):
            msg = (f'Too many upload batches in a short time (limit: {rate_limit.describe_limit("upload")}). '
                   'Please wait a few minutes and try again.')
            if _wants_json_response(request):
                return JsonResponse({'ok': False, 'error': msg}, status=429)
            messages.error(request, msg)
            return redirect('documents:bulk_upload')

        max_bulk = _bulk_upload_max_files()
        all_files = request.FILES.getlist('files')
        cap_msg = ''
        if len(all_files) > max_bulk:
            cap_msg = (
                f'Only the first {max_bulk} file(s) are processed per batch; '
                f'{len(all_files) - max_bulk} additional file(s) were not uploaded.'
            )
            if not _wants_json_response(request):
                messages.info(request, cap_msg)
        files = all_files[:max_bulk]
        if not files:
            if _wants_json_response(request):
                return JsonResponse({'ok': False, 'error': 'No files selected.'}, status=400)
            messages.warning(request, 'No files selected.')
            return redirect('documents:bulk_upload')

        from datetime import datetime
        from qa_mapping.models import QAProgram

        program_pk = request.POST.get('program') or None
        program_obj = None
        if program_pk:
            program_obj = QAProgram.objects.filter(pk=program_pk).first()

        # Faculty: tag every file in the batch to one of their assigned areas.
        area_scope = faculty_area_scope(request.user)
        faculty_qa_area = ''
        faculty_acc_area = None
        if area_scope is not None:
            codes = area_scope
            if not codes:
                msg = 'No accreditation area is assigned to your account. Contact the administrator.'
                if _wants_json_response(request):
                    return JsonResponse({'ok': False, 'error': msg}, status=400)
                messages.error(request, msg)
                return redirect('documents:repository')
            requested = (request.POST.get('qa_area') or '').strip()
            if requested not in set(codes):
                requested = codes[0] if len(codes) == 1 else ''
            if not requested:
                msg = 'Please choose which assigned area these files belong to.'
                if _wants_json_response(request):
                    return JsonResponse({'ok': False, 'error': msg}, status=400)
                messages.error(request, msg)
                return redirect('documents:bulk_upload')
            faculty_qa_area = requested
            from qa_structure.models import AccreditationArea
            faculty_acc_area = AccreditationArea.objects.filter(area_code=requested).first()

        from ai_processing.image_hash import is_image_file

        uploaded_doc_ids = []
        uploaded_filenames = []
        rejected_filenames = []
        errors = []
        allowed_ext = ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png']

        for f in files:
            filename = f.name
            ext = os.path.splitext(filename)[1].lower()

            if ext not in allowed_ext:
                errors.append(f'{filename}: unsupported file type "{ext}"')
                rejected_filenames.append(filename)
                continue

            if f.size > 25 * 1024 * 1024:
                errors.append(f'{filename}: file exceeds 25MB limit')
                rejected_filenames.append(filename)
                continue

            problem = upload_content_problem(f, ext)
            if problem:
                errors.append(f'{filename}: {problem}')
                rejected_filenames.append(filename)
                continue

            # Hashed once, and the hash is stored on the document, so nothing
            # reads the file again later just to hash it.
            content_hash = _sha256_uploaded_file(f)
            if _is_exact_duplicate_upload(f, ext, uploaded_hash=content_hash):
                errors.append(f'{filename}: Exact duplicate file already exists in the repository')
                rejected_filenames.append(filename)
                continue
            # Near-duplicate *text* is checked in the background once the file's
            # text has been extracted (documents/jobs.py). Checking it here meant
            # OCR inside the request, for every file, before any was saved: a
            # 32-file batch held the browser for 99 seconds.
            image_hash = _compute_uploaded_image_hash(f) if is_image_file(ext) else ''
            # Files saved earlier in this same request are left to the pipeline's
            # visual check, which flags them for review -- as it always has.
            vis_doc, vis_pct = _visual_duplicate_match(
                f, ext, candidate=image_hash, exclude_ids=uploaded_doc_ids)
            if vis_doc is not None:
                errors.append(f'{filename}: This is the same picture as one already archived ({vis_pct}% of it matches '
                              f'{matched_document_label(request.user, vis_doc)})')
                rejected_filenames.append(filename)
                continue

            try:
                doc = Document(
                    # The title column holds 255 characters; MySQL refuses a
                    # longer value where SQLite quietly stored it.
                    title=os.path.splitext(filename)[0][:255],
                    file=f,
                    file_type=ext.lstrip('.'),
                    year=datetime.now().year,
                    document_type='Document',
                    uploaded_by=request.user,
                    program=program_obj,
                    qa_area=faculty_qa_area,
                    acc_area=faculty_acc_area,
                    is_processed=False,
                    content_sha256=content_hash,
                    image_phash=image_hash,
                )
                doc.save()
                uploaded_doc_ids.append(doc.pk)
                uploaded_filenames.append(filename)
            except Exception as e:
                logger.error(f'Bulk upload error for {filename}: {e}')
                errors.append(f'{filename}: {str(e)}')
                rejected_filenames.append(filename)

        job = None
        if uploaded_doc_ids:
            job = enqueue_job(
                'bulk_upload_process',
                payload={
                    'document_ids': uploaded_doc_ids,
                    'filenames': uploaded_filenames,
                    'total_count': len(uploaded_doc_ids),
                    'processed_count': 0,
                    'errors': [],
                },
                created_by=request.user,
                inline=False,
            )

        if _wants_json_response(request):
            # Files past the batch cap were dropped without a word when the
            # upload came from the page (the browser caps a batch too; this is
            # for one that got past it).
            for extra in all_files[max_bulk:]:
                errors.append(f'{extra.name}: not uploaded - only {max_bulk} files are accepted per batch')
                rejected_filenames.append(extra.name)
            if not uploaded_doc_ids:
                return JsonResponse({'ok': False, 'errors': errors, 'rejected_filenames': rejected_filenames}, status=400)
            return JsonResponse({
                'ok': True,
                'job_id': job.pk if job else None,
                'uploaded_count': len(uploaded_doc_ids),
                'filenames': uploaded_filenames,
                'rejected_filenames': rejected_filenames,
                'errors': errors,
                'message': (
                    f'{len(uploaded_doc_ids)} file(s) uploaded. '
                    'We will notify you when processing finishes.'
                ),
            })

        if job:
            messages.success(
                request,
                f'{len(uploaded_doc_ids)} document(s) uploaded. '
                'We will notify you when they are ready.',
            )
        if errors:
            messages.warning(
                request,
                f'{len(errors)} file(s) could not be uploaded. Please check the file(s) and try again.',
            )
        return redirect('documents:repository')

    from qa_mapping.models import QAProgram
    programs = QAProgram.objects.filter(is_active=True)
    area_scope = faculty_area_scope(request.user)
    if area_scope is not None and not area_scope:
        # A Faculty account with no area could only pick "- Select your area -"
        # and was refused after choosing files. Same guidance as the single-file page.
        messages.warning(
            request,
            'No accreditation area is assigned to your account yet. Please contact the administrator.',
        )
        return redirect('documents:repository')
    return render(
        request,
        'documents/bulk_upload.html',
        {
            'programs': programs,
            'bulk_upload_max_files': _bulk_upload_max_files(),
            'is_faculty_upload': area_scope is not None,
            'faculty_area_codes': area_scope or [],
            'faculty_single_area': area_scope[0] if area_scope and len(area_scope) == 1 else None,
        },
    )


@login_required
@repository_access_required
def job_status(request, pk):
    """Return JSON status for a background job owned by the current user."""
    job = get_object_or_404(BackgroundJob, pk=pk)
    if not _job_owned_by_user(job, request.user) and not request.user.is_superuser:
        raise Http404
    return JsonResponse(serialize_job(job))


@login_required
def upload_batches(request):
    """
    The current user's recent upload batches, assembled from the server's own
    rows rather than from anything the browser kept.

    This is what lets the upload page show the true state of a batch after a
    navigation, a refresh, a new tab, or a fresh login.
    """
    from .upload_batches import recent_batches

    return JsonResponse({'batches': recent_batches(request.user)})


@login_required
@repository_access_required
def jobs_active(request):
    """List pending/running jobs for the current user (for navbar polling)."""
    jobs = BackgroundJob.objects.filter(
        created_by=request.user,
        status__in=('pending', 'running'),
    ).order_by('-created_at')[:10]
    return JsonResponse({'jobs': [serialize_job(j) for j in jobs]})


@login_required
@qa_staff_required
def structured_upload(request):
    """
    Single-document upload with manual metadata and the accreditation area.

    The area is what decides which faculty can later see the document.
    """
    from datetime import datetime

    from qa_mapping.models import QAProgram
    from qa_structure.models import AccreditationArea
    from .text_extraction import extract_text
    from .ai_pipeline import run_full_ai_pipeline

    programs = QAProgram.objects.filter(is_active=True)
    areas = AccreditationArea.objects.all()

    if request.method == 'POST':
        form = StructuredDocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES.get('file')
            file_ext = os.path.splitext(uploaded_file.name)[1].lower() if uploaded_file else ''
            if uploaded_file and _is_exact_duplicate_upload(uploaded_file, file_ext):
                form.add_error('file', 'Exact duplicate file already exists in the repository.')
                messages.error(request, 'Upload blocked: duplicate file detected.')
                return render(request, 'documents/structured_upload.html', {
                    'form': form,
                    'programs': programs,
                    'areas': areas,
                })
            if uploaded_file and _is_near_duplicate_upload(uploaded_file, file_ext):
                form.add_error('file', 'Near-duplicate content detected (very similar to an existing document).')
                messages.error(request, 'Upload blocked: near-duplicate content detected.')
                return render(request, 'documents/structured_upload.html', {
                    'form': form,
                    'programs': programs,
                    'areas': areas,
                })
            if uploaded_file:
                vis_doc, vis_pct = _visual_duplicate_match(uploaded_file, file_ext)
                if vis_doc is not None:
                    form.add_error('file', f'This is the same picture as one already archived ({vis_pct}% of it matches '
                                           f'{matched_document_label(request.user, vis_doc)}).')
                    messages.error(request, f'Upload blocked: visually similar image detected ({vis_pct}% match).')
                    return render(request, 'documents/structured_upload.html', {
                        'form': form,
                        'programs': programs,
                        'areas': areas,
                    })

            doc = form.save(commit=False)
            doc.uploaded_by = request.user
            doc.file_type = os.path.splitext(doc.file.name)[1].lower().lstrip('.') if doc.file else 'pdf'
            doc.save()

            problem = ''
            if doc.file and hasattr(doc.file, 'path') and os.path.exists(doc.file.path):
                problem = _store_extracted_text(doc)

                from ai_processing.image_hash import is_image_file, compute_image_hash
                if is_image_file(doc.file_type):
                    phash = compute_image_hash(doc.file.path)
                    if phash:
                        doc.image_phash = phash
                        doc.save(update_fields=['image_phash'])

            try:
                if bool(getattr(settings, 'AI_USE_BACKGROUND_JOBS', True)):
                    enqueue_job(
                        'full_ai_pipeline',
                        payload={},
                        created_by=request.user,
                    )
                else:
                    run_full_ai_pipeline(request)
            except Exception as exc:
                logger.warning('Post-upload full AI failed: %s', exc)

            ActivityLog.objects.create(
                user=request.user,
                action='structured_upload',
                description=f'Structured upload: {doc.title}',
            )
            if problem:
                messages.warning(request, f'Document saved, but: {problem}')
            else:
                messages.success(request, 'Document uploaded and linked to the accreditation structure.')
            return redirect('documents:repository')
    else:
        form = StructuredDocumentUploadForm(initial={'year': datetime.now().year})

    return render(request, 'documents/structured_upload.html', {
        'form': form,
        'programs': programs,
        'areas': areas,
    })


def _store_extracted_text(doc):
    """
    Put the saved file's text on the document, with the reason when none came out.

    Returns the problem when the file itself cannot be read (it is then recorded
    as a processing error), else ''. A damaged Word file used to be stored as a
    successful upload with no text, and a missing Tesseract or an oversized scan
    left only "OCR/extraction produced no text.".
    """
    from .text_extraction import explain_extraction, is_damaged_file_problem

    extracted, method = extract_text(doc.file.path)
    try:
        problem, notice = explain_extraction(doc.file.path, extracted, method)
    except Exception:  # the explanation is a courtesy; it never fails the upload
        problem, notice = '', ''
    if extracted:
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
        doc.processing_error = problem
        doc.save(update_fields=['processing_error'])
        return problem
    elif method in ('ocr_failed', 'pdf_extraction') or problem:
        doc.ocr_status = 'failed'
        doc.ocr_error = problem or notice or 'OCR/extraction produced no text.'
        doc.save(update_fields=['ocr_status', 'ocr_error'])
    return ''


def _finalize_uploaded_document(request, doc):
    """
    Run text extraction, image hashing and the AI pipeline for a freshly saved
    upload. Returns the problem when the file cannot be read, else ''.
    """
    from ai_processing.image_hash import is_image_file, compute_image_hash
    from .ai_pipeline import run_full_ai_pipeline

    problem = ''
    if doc.file and hasattr(doc.file, 'path') and os.path.exists(doc.file.path):
        problem = _store_extracted_text(doc)

        if is_image_file(doc.file_type):
            phash = compute_image_hash(doc.file.path)
            if phash:
                doc.image_phash = phash
                doc.save(update_fields=['image_phash'])

    try:
        if bool(getattr(settings, 'AI_USE_BACKGROUND_JOBS', True)):
            enqueue_job('full_ai_pipeline', payload={}, created_by=request.user)
        else:
            run_full_ai_pipeline(request)
    except Exception as exc:
        logger.warning('Post-upload full AI failed: %s', exc)
    return problem


@login_required
@faculty_required
def faculty_upload(request):
    """Single-file upload for Faculty, restricted to their assigned accreditation area(s)."""
    from datetime import datetime
    from qa_mapping.models import QAProgram
    from qa_structure.models import AccreditationArea

    codes = faculty_assigned_area_codes(request.user)
    is_admin_preview = request.user.is_superuser or getattr(
        getattr(request.user, 'profile', None), 'role', '') == 'admin'
    if not codes and not is_admin_preview:
        messages.warning(
            request,
            'No accreditation area is assigned to your account yet. Please contact the administrator.',
        )
        return redirect('documents:repository')
    if is_admin_preview and not codes:
        codes = list(AccreditationArea.objects.values_list('area_code', flat=True))

    programs = QAProgram.objects.filter(is_active=True)

    if request.method == 'POST':
        form = FacultyUploadForm(request.POST, request.FILES, allowed_area_codes=codes)
        if form.is_valid():
            uploaded_file = request.FILES.get('file')
            file_ext = os.path.splitext(uploaded_file.name)[1].lower() if uploaded_file else ''

            blocked = False
            if uploaded_file and _is_exact_duplicate_upload(uploaded_file, file_ext):
                form.add_error('file', 'Exact duplicate file already exists in the repository.')
                messages.error(request, 'Upload blocked: duplicate file detected.')
                blocked = True
            elif uploaded_file and _is_near_duplicate_upload(uploaded_file, file_ext):
                form.add_error('file', 'Near-duplicate content detected (very similar to an existing document).')
                messages.error(request, 'Upload blocked: near-duplicate content detected.')
                blocked = True
            elif uploaded_file:
                vis_doc, vis_pct = _visual_duplicate_match(uploaded_file, file_ext)
                if vis_doc is not None:
                    form.add_error('file', f'This is the same picture as one already archived ({vis_pct}% of it matches '
                                           f'{matched_document_label(request.user, vis_doc)}).')
                    messages.error(request, f'Upload blocked: visually similar image detected ({vis_pct}% match).')
                    blocked = True

            if not blocked:
                doc = form.save(commit=False)
                doc.uploaded_by = request.user
                doc.file_type = os.path.splitext(doc.file.name)[1].lower().lstrip('.') if doc.file else 'pdf'
                area_obj = AccreditationArea.objects.filter(area_code=doc.qa_area).first()
                if area_obj:
                    doc.acc_area = area_obj
                doc.save()

                problem = _finalize_uploaded_document(request, doc)

                ActivityLog.objects.create(
                    user=request.user,
                    action='faculty_upload',
                    description=f'Faculty upload ({doc.qa_area}): {doc.title}',
                )
                if problem:
                    messages.warning(request, f'Document "{doc.title}" was saved to {doc.qa_area}, but: {problem}')
                else:
                    messages.success(request, f'Document "{doc.title}" uploaded to {doc.qa_area}.')
                return redirect('documents:repository')
    else:
        form = FacultyUploadForm(initial={'year': datetime.now().year}, allowed_area_codes=codes)

    return render(request, 'documents/faculty_upload.html', {
        'form': form,
        'programs': programs,
        'area_codes': codes,
        'single_area': codes[0] if len(codes) == 1 else None,
    })


REPOSITORY_PAGE_SIZE = 25

_REPO_SORT_FIELDS = {
    'title': 'title',
    'type': 'file_type',
    'year': 'year',
    'cluster': 'cluster_label',
    'uploaded': 'uploaded_at',
}


def _repo_area_filter_choices(area_codes):
    """Build sorted area dropdown options with code + display name."""
    from qa_structure.models import AccreditationArea
    from qa_structure.utils_ordering import area_roman_sort_key

    codes = {c for c in area_codes if c}
    if not codes:
        return []
    names = dict(
        AccreditationArea.objects.filter(area_code__in=codes).values_list('area_code', 'area_name')
    )
    choices = []
    for code in codes:
        name = (names.get(code) or '').strip()
        label = f'{code} — {name}' if name else code
        choices.append({'code': code, 'name': name, 'label': label})
    choices.sort(key=lambda item: area_roman_sort_key(item['code']))
    return choices


def _repo_area_filter_label(area_code, area_filters):
    if not area_code:
        return ''
    for item in area_filters or []:
        if item['code'] == area_code:
            return item['label']
    return area_code


def _repo_active_filters(request, *, query, year, file_type, duplicate, cluster, program, programs, area=None,
                         area_filters=None, uploaded=None):
    """Build removable filter chips for the repository UI."""
    from django.urls import reverse

    base = reverse('documents:repository')
    params = request.GET.copy()
    chips = []

    def chip(key, label):
        p = params.copy()
        p.pop(key, None)
        p.pop('page', None)
        qs = p.urlencode()
        return {'key': key, 'label': label, 'remove_url': f'{base}?{qs}' if qs else base}

    if query:
        chips.append(chip('q', f'Search: {query}'))
    if program and str(program).isdigit():
        prog = programs.filter(pk=int(program)).first()
        chips.append(chip('program', f'Program: {prog.code if prog else program}'))
    if area:
        chips.append(chip('area', f'Area: {_repo_area_filter_label(area, area_filters)}'))
    if year:
        chips.append(chip('year', f'Year: {year}'))
    if file_type:
        chips.append(chip('file_type', f'Format: {str(file_type).upper()}'))
    if cluster:
        chips.append(chip('cluster', f'Cluster: {cluster}'))
    if duplicate:
        dup_labels = {
            'review': 'Duplicates to review',
            'none': 'Duplicate: Clear',
            'pending_check': 'Duplicate: Checking…',
            'possible': 'Duplicate: Needs review',
            'confirmed_dup': 'Duplicate: Confirmed duplicate',
        }
        chips.append(chip('duplicate', dup_labels.get(duplicate, f'Duplicate: {duplicate}')))
    if uploaded:
        chips.append(chip('uploaded', 'Uploaded: last 7 days'))
    return chips


def _apply_repo_sort(qs, sort_key, sort_dir):
    field = _REPO_SORT_FIELDS.get(sort_key)
    if not field:
        return qs
    prefix = '-' if sort_dir == 'desc' else ''
    # '-id' is the final tie-break, and it is what puts a just-uploaded document at
    # the top of the list. A bulk upload writes several rows in the same instant, so
    # they share an uploaded_at value; with only the timestamp to sort on the tie is
    # unresolved and the database returns those rows in whatever order it likes -
    # in practice oldest-first, and not guaranteed to be stable between backends.
    # Ordering by descending primary key after it means the newest row always wins.
    return qs.order_by(f'{prefix}{field}', '-uploaded_at', '-id')


@login_required
@repository_access_required
def repository_list(request):
    """List documents with filters, pagination, AJAX partials, and infinite-scroll support."""
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from search.search_service import search_documents

    from qa_mapping.models import QAProgram

    query = request.GET.get('q', '').strip()
    year = request.GET.get('year')
    file_type = request.GET.get('file_type')
    duplicate = request.GET.get('duplicate')
    cluster = request.GET.get('cluster')
    program = request.GET.get('program')
    area = (request.GET.get('area') or '').strip()
    show_archived = False
    # A search is listed best match first unless a column sort was picked. The
    # search ranks its results, and the repository used to re-sort every one of
    # them by upload date, so a title match could sit below pages of passing
    # mentions.
    sort_explicit = request.GET.get('sort', '') in _REPO_SORT_FIELDS
    if sort_explicit:
        sort_key = request.GET['sort']
    else:
        sort_key = 'relevance' if query else 'uploaded'
    sort_dir = request.GET.get('dir', 'desc')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    # Duplicate review filters are QA Head / Admin only (not faculty via URL param).
    if faculty_area_scope(request.user) is not None:
        duplicate = None
    # "Uploaded This Week" on the dashboard opens this filter (last 7 days).
    uploaded = '7d' if request.GET.get('uploaded') == '7d' else ''

    filters = {
        'year': year,
        'file_type': file_type,
        'duplicate': duplicate,
        'cluster': cluster,
        'program': program,
    }
    filters = {k: v for k, v in filters.items() if v}

    # Faculty members only ever see documents in their assigned area(s).
    # QA Head / Admin may consolidate by picking a specific accreditation area.
    area_scope = faculty_area_scope(request.user)
    if area_scope is not None:
        allowed_areas = area_scope or []
        if area and area in allowed_areas:
            filters['area_codes'] = [area]
        else:
            area = ''
            filters['area_codes'] = allowed_areas if allowed_areas else [NO_AREA_SENTINEL]
    else:
        if area:
            filters['area_codes'] = [area]

    documents_qs = search_documents(query, filters, include_archived=show_archived)
    if uploaded:
        from datetime import timedelta
        from django.utils import timezone
        documents_qs = documents_qs.filter(uploaded_at__gte=timezone.now() - timedelta(days=7))
    documents_qs = documents_qs.select_related('uploaded_by', 'uploaded_by__profile', 'program', 'acc_area')
    if sort_key != 'relevance':
        documents_qs = _apply_repo_sort(documents_qs, sort_key, sort_dir)

    try:
        page_number = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page_number = 1

    paginator = Paginator(documents_qs, REPOSITORY_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)

    base_qs = scope_documents_for_user(Document.objects.filter(is_archived=False), request.user)
    years = base_qs.values_list('year', flat=True).distinct().order_by('-year')
    file_types = base_qs.exclude(file_type='').values_list('file_type', flat=True).distinct().order_by('file_type')
    clusters = base_qs.exclude(cluster_label__isnull=True).values_list('cluster_label', flat=True).distinct().order_by('cluster_label')
    programs = QAProgram.objects.filter(is_active=True)

    # Accreditation areas available for the "Area" consolidation filter. Built from
    # registered accreditation areas plus any free-text qa_area values already in scope.
    from qa_structure.models import AccreditationArea
    area_codes_set = set(
        c for c in AccreditationArea.objects.values_list('area_code', flat=True) if c
    )
    area_codes_set.update(
        c for c in base_qs.exclude(qa_area='').values_list('qa_area', flat=True) if c
    )
    if area_scope is not None:
        area_codes_set &= set(area_scope or [])
    area_filters = _repo_area_filter_choices(area_codes_set)
    current_program_obj = None
    if program and str(program).isdigit():
        current_program_obj = programs.filter(pk=int(program)).first()

    # Facet counts are not computed here: nothing on the page shows them, and they
    # cost five more searches per request.
    active_filters = _repo_active_filters(
        request,
        query=query,
        year=year,
        file_type=file_type,
        duplicate=duplicate,
        cluster=cluster,
        program=program,
        programs=programs,
        area=area,
        area_filters=area_filters,
        uploaded=uploaded,
    )

    total_count = paginator.count
    has_more = page_obj.has_next()
    next_page = page_obj.next_page_number() if has_more else None

    context = {
        'documents': page_obj.object_list,
        'total_count': total_count,
        'page_obj': page_obj,
        'has_more': has_more,
        'next_page': next_page,
        'page_number': page_number,
        'repository_page_size': REPOSITORY_PAGE_SIZE,
        'query': query,
        'years': years,
        'file_types': file_types,
        'clusters': clusters,
        # Descriptive name of each cluster number, shown on hover wherever the number is.
        'cluster_names': _cluster_names(),
        'programs': programs,
        'areas': area_filters,
        'area_filters': area_filters,
        'current_area': area,
        'current_year': year,
        'current_file_type': file_type,
        'current_duplicate': duplicate,
        'current_cluster': cluster,
        'current_uploaded': uploaded,
        'current_program': program,
        'current_program_obj': current_program_obj,
        'active_filters': active_filters,
        'current_sort': sort_key,
        'current_sort_dir': sort_dir,
        'sort_explicit': sort_explicit,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('documents/repository_table_partial.html', context, request=request)
        if query or filters or show_archived or uploaded:
            count_html = f'Found <strong>{total_count}</strong> result{"s" if total_count != 1 else ""}'
        else:
            count_html = f'<strong>{total_count}</strong> document{"s" if total_count != 1 else ""} total'
        if has_more:
            count_html += ' <span class="text-muted">· scroll the document list for more</span>'
        return JsonResponse(
            {
                'html': html,
                'count_html': count_html,
                'has_more': has_more,
                'next_page': next_page,
                'page': page_number,
                'total': total_count,
            }
        )

    return render(request, 'documents/repository.html', context)


def _similarity_summary(doc, rows):
    """
    One line that answers the panel's question before the list does.

    A reader opening a flagged document was given five or seven rows that each
    repeated the same sentence, and nothing anywhere said whether the decision
    those rows exist for had been taken. This states the count, the range of the
    measurements, and the decision -- so the list below it becomes the evidence
    for a stated answer rather than the answer itself.
    """
    if not rows:
        return None

    percents = [row['similarity'] for row in rows]
    low, high = min(percents), max(percents)
    band = f'{low:.0f}%' if round(low) == round(high) else f'{low:.0f}–{high:.0f}%'

    reviewed = [row['reviewed_at'] for row in rows if row.get('reviewed_at')]
    when = ''
    if reviewed:
        stamp = parse_datetime(max(reviewed))
        if stamp is not None:
            if timezone.is_aware(stamp):
                stamp = timezone.localtime(stamp)
            when = stamp.strftime('%b %d, %Y')

    status = doc.duplicate_status
    if status == 'confirmed_dup':
        state, tone = 'Reviewed — confirmed as a duplicate', 'danger'
    elif status == 'possible':
        state, tone = 'Not reviewed yet', 'warning'
    elif any(row.get('review') == 'dismissed' for row in rows):
        state, tone = 'Reviewed — kept as separate versions', 'success'
    else:
        state, tone = '', ''

    return {
        'count': len(rows),
        'band': band,
        'measure': 'of the wording' if all(r['match_type'] == 'text' for r in rows)
                   else 'similar',
        'state': state,
        'tone': tone,
        'when': when,
        # A decided list is history; an undecided one is the thing being decided.
        'settled': status != 'possible' and bool(state),
    }


def _describe_similarity(doc, other, match):
    """
    One row of "Similar Documents", said in terms a reader can check.

    The percentage used to be rendered with `floatformat:0`, so a text match of
    0.9975 printed as "100% match" on two files that are not the same file --
    and no two documents in the archive share a content hash, because an exact
    copy is refused at upload. A hundred per cent is reserved for a file that
    really is byte-for-byte the same, and everything else is shown for what it
    is, with the reason it was allowed in.

    The number itself now comes from `verified_text_matches`, which measures the
    two documents as they are written rather than from the corpus-wide TF-IDF
    matrix, so a reader who opens both files can see the wording it claims.

    A match a staff member has already ruled on says so. The decision was kept
    on the match all along (`review`), but nothing displayed it, so a dismissed
    pair went on reading like an open question.
    """
    raw = float(match.get('similarity', 0) or 0)
    kind = match.get('match_type', 'text')
    identical = bool(doc.content_sha256 and doc.content_sha256 == other.content_sha256)
    percent = 100.0 if identical else min(99.0, raw * 100)

    if kind == 'visual':
        measure = 'of the picture matches'
        label = 'Visual'
    elif kind == 'visual_review':
        measure = 'of the picture matches'
        label = 'Visual (to review)'
    elif kind == 'visual_named':
        measure = 'visually alike, and the file names match'
        label = 'Visual (by name)'
    else:
        measure = 'of the wording matches'
        label = 'Text'

    subject = 'picture' if kind.startswith('visual') else 'wording'
    if identical:
        note = 'The same file, stored twice.'
    elif percent >= 99:
        note = (f'Nearly all the {subject} is the same, but the files differ '
                '— kept as a separate version for review.')
    elif percent >= 95:
        note = f'Most of the {subject} is the same; most likely another draft of the same document.'
    else:
        note = 'Related content; kept as its own document.'

    review = match.get('review')
    if review == 'confirmed':
        decision = 'Reviewed: confirmed as a duplicate.'
    elif review == 'dismissed':
        decision = 'Reviewed: not a duplicate.'
    else:
        decision = ''

    return {
        'document': other,
        'similarity': percent,
        'match_type': kind,
        'match_label': label,
        'measure': measure,
        'note': note,
        'identical': identical,
        'decision': decision,
        'review': review or '',
        'reviewed_at': match.get('reviewed_at') or '',
    }


@login_required
@repository_access_required
def document_detail(request, pk):
    """View document details including AI processing results and version history."""
    doc = get_object_or_404(Document, pk=pk)
    if not user_can_access_document(request.user, doc):
        messages.error(request, 'That document is outside your assigned area(s).')
        return redirect('documents:repository')

    # Only documents this viewer may open, and no archived versions: a Faculty
    # member was listed matches and cluster peers from other areas.
    #
    # The list is counted before it is cut. Nine near-identical drafts of one
    # manuscript showed as five rows with no sign that four more existed, and
    # because the titles are long and alike the five looked like the same row
    # repeated. The panel now says how many there are and shows enough of each
    # to tell them apart.
    # Duplicate work is QA work. A Faculty member cannot confirm or dismiss a
    # match, and the Repository already hides the Duplicate column from them, so
    # the matches are not merely hidden in the template -- they are never put in
    # the page. Hiding a panel while shipping its contents in the HTML is not
    # scoping. Cluster peers go the same way: the Clusters page is staff only.
    staff_view = not is_faculty(request.user)
    matches = [m for m in (doc.similar_documents or []) if isinstance(m, dict)] if staff_view else []
    by_id = {
        d.pk: d for d in Document.objects.filter(
            pk__in=[m.get('id') for m in matches if m.get('id')], is_archived=False)
    }
    visible = []
    for match in matches:
        sim_doc = by_id.get(match.get('id'))
        if sim_doc is None or not user_can_access_document(request.user, sim_doc):
            continue
        visible.append(_describe_similarity(doc, sim_doc, match))
    similar_total = len(visible)
    similar_docs = visible[:5]
    similar_summary = _similarity_summary(doc, visible)

    cluster_docs = []
    if staff_view and doc.cluster_label is not None:
        cluster_docs = scope_documents_for_user(
            Document.objects.filter(cluster_label=doc.cluster_label, is_archived=False), request.user,
        ).exclude(pk=doc.pk)[:5]

    version_chain = doc.version_chain()
    can_manage_versions = (
        getattr(getattr(request.user, 'profile', None), 'role', '') in ('admin', 'qa_staff')
    )
    candidate_older_docs = []
    if can_manage_versions:
        candidate_older_docs = Document.objects.exclude(pk=doc.pk).exclude(
            superseded_by=doc
        ).order_by('-uploaded_at')[:200]

    context = {
        'document': doc,
        'similar_docs': similar_docs,
        'similar_total': similar_total,
        'similar_summary': similar_summary,
        'cluster_docs': cluster_docs,
        'version_chain': version_chain,
        'can_manage_versions': can_manage_versions,
        'candidate_older_docs': candidate_older_docs,
    }

    if request.GET.get('panel') == '1':
        return render(request, 'documents/detail_panel.html', context)

    return render(request, 'documents/detail.html', context)


def _wants_json(request) -> bool:
    """Asked for from the details modal rather than from the page itself."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _decision_response(request, doc, note):
    """
    Answer a decision the way it was asked for.

    From the standalone page: the message is queued and the browser is sent back
    to the document, as it always was. From the modal: JSON, and *no* queued
    message -- a message nobody renders is not discarded, it waits and appears
    at the top of whatever page is opened next, minutes later and out of
    context. The modal shows its own confirmation instead.
    """
    if _wants_json(request):
        return JsonResponse({
            'ok': True,
            'duplicate_status': doc.duplicate_status,
            'badge': render_to_string('documents/_duplicate_status_badge.html',
                                      {'status': doc.duplicate_status}),
            'message': note,
        })
    messages.success(request, note)
    return redirect('documents:detail', pk=doc.pk)


@login_required
@qa_staff_required
def mark_duplicate_confirmed(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == 'POST':
        from .ai_pipeline import REVIEW_CONFIRMED, record_duplicate_review

        # Kept on each listed match, so the next AI run leaves the decision alone.
        record_duplicate_review(doc, REVIEW_CONFIRMED)
        ActivityLog.objects.create(user=request.user, action='duplicate_confirmed', description=f'Confirmed duplicate: {doc.title}')
        return _decision_response(request, doc, 'Marked as a confirmed duplicate.')
    return redirect('documents:detail', pk=pk)


@login_required
@qa_staff_required
def dismiss_duplicate(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == 'POST':
        from .ai_pipeline import REVIEW_DISMISSED, record_duplicate_review

        # Kept on each listed match: the next AI run neither re-flags this
        # document for them nor announces them again.
        record_duplicate_review(doc, REVIEW_DISMISSED)
        ActivityLog.objects.create(user=request.user, action='duplicate_dismissed', description=f'Dismissed duplicate flag: {doc.title}')
        return _decision_response(request, doc, 'Cleared — kept as a separate version.')
    return redirect('documents:detail', pk=pk)


@login_required
@qa_staff_required
def retry_ocr(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == 'POST' and doc.file_type in ('docx', 'xlsx'):
        # OCR reads pictures of text; a Word or Excel file's text is read directly.
        messages.info(request, 'OCR does not apply to Word or Excel files - their text is read directly.')
        return redirect('documents:detail', pk=pk)
    if request.method == 'POST':
        doc.ocr_status = 'retrying'
        doc.ocr_error = ''
        doc.save(update_fields=['ocr_status', 'ocr_error'])
        enqueue_job(
            'reprocess_ocr',
            payload={'only_empty': False, 'pdf_only': False, 'document_ids': [doc.pk]},
            created_by=request.user,
        )
        ActivityLog.objects.create(user=request.user, action='retry_ocr', description=f'OCR retry queued for: {doc.title}')
        messages.success(request, 'OCR retry queued.')
    return redirect('documents:detail', pk=pk)


@login_required
@qa_staff_required
def mark_as_version(request, pk):
    """
    Mark `pk` as a newer version that supersedes another document.

    POST: previous_id — the older document to archive and link as previous_version.
    """
    doc = get_object_or_404(Document, pk=pk)
    if request.method != 'POST':
        return redirect('documents:detail', pk=pk)

    previous_id = request.POST.get('previous_id')
    if not previous_id:
        messages.warning(request, 'Please choose the older document this one replaces.')
        return redirect('documents:detail', pk=pk)

    try:
        older = Document.objects.get(pk=int(previous_id))
    except (Document.DoesNotExist, ValueError, TypeError):
        messages.error(request, 'Older document not found.')
        return redirect('documents:detail', pk=pk)

    if older.pk == doc.pk:
        messages.error(request, 'A document cannot supersede itself.')
        return redirect('documents:detail', pk=pk)

    # A cycle forms when this document is already among the older one's own
    # earlier versions. The check used to walk back from this document instead,
    # so "B supersedes A" followed by "A supersedes B" was accepted.
    walker = older
    seen = set()
    while walker is not None and walker.pk not in seen:
        if walker.pk == doc.pk:
            messages.error(request, 'That would create a version cycle.')
            return redirect('documents:detail', pk=pk)
        seen.add(walker.pk)
        walker = walker.previous_version

    doc.previous_version = older
    doc.is_archived = False
    doc.save(update_fields=['previous_version', 'is_archived'])

    older.is_archived = True
    older.save(update_fields=['is_archived'])

    ActivityLog.objects.create(
        user=request.user,
        action='version_supersede',
        description=f'"{doc.title}" now supersedes "{older.title}" (archived).',
    )
    try:
        from notifications.services import notify_qa_staff
        from notifications.user_messages import version_supersede_message
        notify_qa_staff(
            version_supersede_message(doc.title, older.title),
            category='upload',
            link=request.build_absolute_uri(f'/documents/{doc.pk}/') if request else '',
        )
    except Exception:
        pass

    messages.success(request, f'"{doc.title}" now supersedes "{older.title}". The older document is archived.')
    return redirect('documents:detail', pk=pk)


@login_required
@qa_staff_required
def unarchive_document(request, pk):
    """
    Restore a previously-archived document as a current one.

    Restoring also takes it out of the version chain: the newer document that
    replaced it stops pointing at it. The link used to stay, so the restored
    document was both current and "an older version", and a later supersede in
    the other direction made a cycle.
    """
    doc = get_object_or_404(Document, pk=pk)
    if request.method == 'POST':
        doc.is_archived = False
        doc.save(update_fields=['is_archived'])
        unlinked = list(doc.superseded_by.all())
        for newer in unlinked:
            newer.previous_version = None
            newer.save(update_fields=['previous_version'])
        ActivityLog.objects.create(
            user=request.user,
            action='version_unarchive',
            description=f'Restored archived document: {doc.title}'
                        + (f' (no longer an older version of "{unlinked[0].title}")' if unlinked else ''),
        )
        messages.success(request, f'"{doc.title}" has been restored from the archive.')
    return redirect('documents:detail', pk=pk)


def _restore_orphaned_version(older_pk, user):
    """
    Bring back the older version of a document that was just deleted.

    It was archived only because the deleted document replaced it; left
    archived, nothing pointed at it any more and no page could reach it.
    """
    if not older_pk:
        return
    older = Document.objects.filter(pk=older_pk, is_archived=True).first()
    if older is None or older.superseded_by.exists():
        return
    older.is_archived = False
    older.save(update_fields=['is_archived'])
    ActivityLog.objects.create(
        user=user,
        action='version_unarchive',
        description=f'Restored "{older.title}": the newer version that replaced it was deleted.',
    )


@login_required
@repository_access_required
def document_download(request, pk):
    """Download a document file."""
    doc = get_object_or_404(Document, pk=pk)
    if not user_can_access_document(request.user, doc):
        raise Http404("File not found.")
    if doc.file and os.path.exists(doc.file.path):
        ActivityLog.objects.create(
            user=request.user,
            action='download',
            description=f'Downloaded: {doc.title}'
        )
        response = FileResponse(open(doc.file.path, 'rb'))
        response['Content-Disposition'] = content_disposition_header(
            as_attachment=True,
            filename=doc.filename or 'download',
        )
        return response
    raise Http404("File not found.")


def _safe_zip_segment(name: str) -> str:
    cleaned = ''.join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in (name or '')).strip('_')
    return cleaned or 'other'


def _doc_area_label(doc) -> str:
    from .area_utils import document_area_code
    return document_area_code(doc) or 'Unassigned'


def _unique_arcname(name, taken):
    """
    A name not yet used in this ZIP, "report (2).pdf" style.

    Only the base name used to be counted, so two "report.pdf" plus a real
    "report (1).pdf" wrote the same entry twice. Compared without case, as the
    folders people extract into usually are.
    """
    root, ext = os.path.splitext(name)
    candidate, n = name, 0
    while candidate.lower() in taken:
        n += 1
        candidate = f'{root} ({n}){ext}'
    taken.add(candidate.lower())
    return candidate


def _write_docs_to_zip(docs, *, group_by_area: bool = False):
    """
    Build a ZIP of the documents' files; returns (file, file_count).

    The ZIP is written to a temporary file on disk, positioned at its start, and
    sent from there in chunks. It used to be built whole in memory, so "all
    areas" over the full archive held every file in RAM at once.
    """
    import tempfile
    import zipfile

    # On the project's drive, not the system temp folder: on this deployment
    # that is a nearly full C: drive, and an "all areas" ZIP is the whole archive.
    spool_dir = getattr(settings, 'ZIP_TEMP_DIR', '') or None
    try:
        if spool_dir:
            os.makedirs(spool_dir, exist_ok=True)
        spool = tempfile.TemporaryFile(dir=spool_dir)
    except OSError:
        spool = tempfile.TemporaryFile()
    taken = set()
    added = 0
    with zipfile.ZipFile(spool, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            if not doc.file:
                continue
            try:
                file_path = doc.file.path
            except (ValueError, NotImplementedError):
                continue
            if not os.path.exists(file_path):
                continue
            basename = doc.filename or os.path.basename(file_path)
            if group_by_area:
                folder = _safe_zip_segment(_doc_area_label(doc))
                arcname = f'{folder}/{basename}'
            else:
                arcname = basename
            zf.write(file_path, arcname=_unique_arcname(arcname, taken))
            added += 1
    spool.seek(0)
    return spool, added


@login_required
@repository_access_required
def download_area_zip(request):
    """Download documents as ZIP — one area, or all areas (folder per area).

    Respects per-user document scoping (faculty get only assigned areas).
    Pass ``area=all`` to download every accessible document grouped by area.
    """
    from django.db.models import Q
    from django.urls import reverse

    area = (request.GET.get('area') or '').strip()
    repo_url = reverse('documents:repository')
    if not area:
        messages.error(request, 'Please choose an accreditation area to download, or use Download all areas.')
        return redirect(repo_url)

    if not rate_limit.allow(request, 'zip'):
        messages.error(request, f'Too many ZIP downloads in a short time (limit: {rate_limit.describe_limit("zip")}). '
                                'Please wait a few minutes and try again.')
        return redirect(repo_url)

    scoped = scope_documents_for_user(
        Document.objects.filter(is_archived=False), request.user
    ).select_related('acc_area')

    if area.lower() == 'all':
        docs = scoped.order_by('qa_area', 'acc_area__area_code', 'title')
        spool, added = _write_docs_to_zip(docs, group_by_area=True)
        if added == 0:
            spool.close()
            messages.warning(request, 'No downloadable files found in your repository scope.')
            return redirect(repo_url)
        ActivityLog.objects.create(
            user=request.user,
            action='download',
            description=f'Downloaded {added} file(s) across all areas as ZIP.',
        )
        return FileResponse(spool, as_attachment=True, filename='qa_documents_by_area.zip',
                            content_type='application/zip')

    area_scope = faculty_area_scope(request.user)
    if area_scope is not None and area not in (area_scope or []):
        raise Http404('Area not available.')

    from .area_utils import build_area_filter_q
    docs = scoped.filter(build_area_filter_q([area]))
    spool, added = _write_docs_to_zip(docs, group_by_area=False)

    if added == 0:
        spool.close()
        messages.warning(request, f'No downloadable files found in {area}.')
        return redirect(f'{repo_url}?area={area}')

    ActivityLog.objects.create(
        user=request.user,
        action='download',
        description=f'Downloaded {added} file(s) for area "{area}" as ZIP.',
    )
    safe_area = _safe_zip_segment(area)
    return FileResponse(spool, as_attachment=True, filename=f'{safe_area}_documents.zip',
                        content_type='application/zip')


# Roman numerals do not sort alphabetically. Ordering the accreditation areas by
# their code as text put "Area IX" between "Area IV" and "Area V", so the grid
# read I, II, III, IV, IX, V, VI, VII, VIII, X -- with the ninth card sitting
# fifth. These read the numeral where the code ends in one.
_ROMAN_VALUES = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def _roman_value(token):
    """The value of a Roman numeral, or None if the token is not one."""
    total = highest = 0
    for char in reversed(token.upper()):
        value = _ROMAN_VALUES.get(char)
        if value is None:
            return None
        total = total - value if value < highest else total + value
        highest = max(highest, value)
    return total or None


def area_sort_key(area_code):
    """Order area codes by their numeral, keeping un-numbered codes together at the end."""
    parts = (area_code or '').split()
    numeral = _roman_value(parts[-1]) if parts else None
    if numeral is None:
        return (1, 0, (area_code or '').lower())
    return (0, numeral, (area_code or '').lower())


# The orders the Clusters page offers. Size first is the default because the
# number K-Means assigns is an index, not a rank -- ordering by it scattered the
# fourteen single-document groups through the grid ahead of the nine-document
# one. But a reader looking for a particular cluster wants it by number, and a
# reader checking what changed wants it by date, so the choice is theirs and the
# page says which one is in force.
CLUSTER_SORTS = {
    'size': 'Largest first',
    'smallest': 'Smallest first',
    'number': 'Cluster number',
    'recent': 'Recently updated',
}
CLUSTER_SORT_DEFAULT = 'size'


def cluster_sort_key(sort):
    """The key function for one of CLUSTER_SORTS, falling back to the default."""
    if sort == 'smallest':
        return lambda c: (c['count'], c['number'])
    if sort == 'number':
        return lambda c: c['number']
    if sort == 'recent':
        # Groups that have never been uploaded to go last, not first.
        return lambda c: (c['last_upload'] is None,
                          -(c['last_upload'].timestamp() if c['last_upload'] else 0),
                          c['number'])
    return lambda c: (-c['count'], c['number'])


def split_cluster_label(label):
    """
    A stored cluster label as its parts: the facets, and the example document.

    `build_cluster_display_label` joins the area, the commonest document type,
    the top terms and an example title into one string with ' . ' between them.
    On a card that string was a single clipped line, and the part that differs
    between clusters -- the example -- comes last, so every one of the
    thirty-two cards was cut off before it said anything a reader could use.
    Twenty-one of them opened with the same three words.

    Splitting on the example marker rather than on every separator keeps a title
    that contains one of its own intact ("SOCIOLOGY . COMPARATIVE ANALYSIS").
    """
    text = (label or '').strip()
    marker = ' · eg. '
    if marker in text:
        head, sample = text.split(marker, 1)
        facets = [p.strip() for p in head.split(' · ') if p.strip()]
    elif text.startswith('eg. '):
        facets, sample = [], text[4:]
    else:
        facets, sample = [p.strip() for p in text.split(' · ') if p.strip()], ''
    return {'facets': facets, 'sample': sample.strip()}


@login_required
@qa_staff_required
def cluster_groups(request):
    """Browse documents grouped by AI cluster (QA Head / Admin)."""
    from django.db.models import Count, Max

    from documents.models import ClusterResult

    base = Document.objects.filter(is_archived=False)
    clustered = base.exclude(cluster_label__isnull=True)

    dist = (
        clustered.values('cluster_label')
        .annotate(count=Count('id'), last=Max('uploaded_at'))
        .order_by('cluster_label')
    )
    label_by_num = {}
    for cr in ClusterResult.objects.order_by('-created_at').values('cluster_number', 'cluster_label'):
        label_by_num.setdefault(cr['cluster_number'], cr['cluster_label'])
    clusters = []
    for row in dist:
        label = label_by_num.get(row['cluster_label']) or f'Cluster {row["cluster_label"]}'
        parts = split_cluster_label(label)
        clusters.append({
            'number': row['cluster_label'],
            'count': row['count'],
            'last_upload': row['last'],
            'display_label': label,
            # The card lays the label out itself: the example document reads as
            # the heading, the facets as quiet meta above it.
            'facets': parts['facets'],
            'sample': parts['sample'],
        })

    # Biggest group first. The order was the cluster number, which is the index
    # K-Means happened to assign -- meaningless to a reader, and it scattered the
    # fourteen single-document groups through the grid ahead of the nine-document
    # one. The number stays on the card as its name; it is an identifier, not a
    # rank. `size_pct` scales each card's bar against the largest group, so the
    # difference between nine documents and one is visible without reading.
    largest = max((c['count'] for c in clusters), default=0)
    for cluster in clusters:
        cluster['size_pct'] = round(cluster['count'] * 100 / largest) if largest else 0

    sort_value = (request.GET.get('sort') or '').strip()
    if sort_value not in CLUSTER_SORTS:
        sort_value = CLUSTER_SORT_DEFAULT
    clusters.sort(key=cluster_sort_key(sort_value))

    selected_raw = (request.GET.get('cluster') or '').strip()
    selected = None
    if selected_raw != '':
        try:
            sel_num = int(selected_raw)
        except (TypeError, ValueError):
            sel_num = None
        if sel_num is not None and any(c['number'] == sel_num for c in clusters):
            docs = (
                clustered.filter(cluster_label=sel_num)
                .select_related('uploaded_by', 'uploaded_by__profile', 'acc_area', 'program')
                .order_by('-uploaded_at')
            )
            selected = {
                'number': sel_num,
                'display_label': label_by_num.get(sel_num) or f'Cluster {sel_num}',
                'documents': docs,
                'count': docs.count(),
            }
        else:
            selected_raw = ''

    summary = {
        'cluster_count': len(clusters),
        'clustered_docs': clustered.count(),
        'unclustered': base.filter(cluster_label__isnull=True).count(),
        # What each card's bar is measured against, and how many groups hold a
        # single document -- fourteen of the thirty-two here, which is worth
        # saying out loud rather than leaving the reader to count the cards.
        'largest_cluster': largest,
        'singletons': sum(1 for c in clusters if c['count'] == 1),
    }

    context = {
        'clusters': clusters,
        'sort_value': sort_value,
        'sort_label': CLUSTER_SORTS[sort_value],
        'sort_options': list(CLUSTER_SORTS.items()),
        'selected': selected,
        'selected_cluster': selected_raw,
        'summary': summary,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'documents/_cluster_detail.html', context)
    return render(request, 'documents/clusters.html', context)


@login_required
@qa_staff_required
def area_submissions(request):
    """QA Head / Admin overview of faculty submissions grouped by accreditation area."""
    from collections import defaultdict
    from django.db.models import Q, Max
    from qa_structure.models import AccreditationArea

    from .area_utils import build_area_filter_q

    base_docs = Document.objects.filter(is_archived=False)

    # One rule for "which area is this document in", shared with the Repository
    # and Faculty access: the linked area when there is one, else the area code
    # text. Matching either field counted a document whose two fields disagree
    # in both areas.
    areas_qs = AccreditationArea.objects.prefetch_related('faculty_profiles__user')
    areas = []
    for area in areas_qs:
        area_docs = base_docs.filter(build_area_filter_q([area.area_code]))
        faculty_ids = [p.user_id for p in area.faculty_profiles.all()]
        faculty_count = len(faculty_ids)
        submitted_count = (
            area_docs.filter(uploaded_by_id__in=faculty_ids)
            .values_list('uploaded_by_id', flat=True).distinct().count()
            if faculty_ids else 0
        )
        areas.append({
            'obj': area,
            'faculty_count': faculty_count,
            'submitted_count': submitted_count,
            'pending_count': max(faculty_count - submitted_count, 0),
            'progress_pct': round(submitted_count * 100 / faculty_count) if faculty_count else 0,
            'file_count': area_docs.count(),
            'last_upload': area_docs.aggregate(m=Max('uploaded_at'))['m'],
        })

    # An area with nobody assigned to it drew the same empty bar as an area whose
    # faculty simply had not submitted yet, labelled "0/0". Those are different
    # states and the card now says which it is.
    areas.sort(key=lambda a: area_sort_key(a['obj'].area_code))

    selected_code = (request.GET.get('area') or '').strip()
    selected = None
    if selected_code:
        selected_obj = next((a['obj'] for a in areas if a['obj'].area_code == selected_code), None)
        if selected_obj is not None:
            area_docs = base_docs.filter(
                build_area_filter_q([selected_obj.area_code])
            ).select_related('uploaded_by', 'uploaded_by__profile').order_by('-uploaded_at')

            docs_by_user = defaultdict(list)
            for doc in area_docs:
                docs_by_user[doc.uploaded_by_id].append(doc)

            faculty_rows = []
            assigned_ids = set()
            for profile in selected_obj.faculty_profiles.select_related('user').all():
                user = profile.user
                assigned_ids.add(user.id)
                user_docs = docs_by_user.get(user.id, [])
                faculty_rows.append({
                    'user': user,
                    'file_count': len(user_docs),
                    'last_upload': user_docs[0].uploaded_at if user_docs else None,
                    'documents': user_docs,
                })
            faculty_rows.sort(
                key=lambda r: (r['user'].get_full_name() or r['user'].username).lower()
            )

            other_rows = []
            for uid, user_docs in docs_by_user.items():
                if uid in assigned_ids:
                    continue
                other_rows.append({
                    'user': user_docs[0].uploaded_by,
                    'file_count': len(user_docs),
                    'last_upload': user_docs[0].uploaded_at,
                    'documents': user_docs,
                })
            other_rows.sort(key=lambda r: r['file_count'], reverse=True)

            selected = {
                'obj': selected_obj,
                'faculty_rows': faculty_rows,
                'other_rows': other_rows,
                'file_count': len(area_docs),
                'submitted_count': sum(1 for r in faculty_rows if r['file_count']),
            }

    summary = {
        'area_count': len(areas),
        'faculty_total': sum(a['faculty_count'] for a in areas),
        'file_total': sum(a['file_count'] for a in areas),
        'areas_with_files': sum(1 for a in areas if a['file_count']),
    }

    context = {
        'areas': areas,
        'summary': summary,
        'selected': selected,
        'selected_code': selected_code,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'documents/_area_submission_detail.html', context)
    return render(request, 'documents/area_submissions.html', context)


@login_required
@repository_access_required
def document_edit(request, pk):
    """Edit document metadata (full page or modal panel via ?panel=1)."""
    doc = get_object_or_404(Document, pk=pk)
    is_panel = request.GET.get('panel') == '1'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not user_can_modify_document(request.user, doc):
        if is_ajax:
            return JsonResponse(
                {'success': False, 'message': 'You can only edit your own uploads within your area(s).'},
                status=403,
            )
        messages.error(request, 'You can only edit your own uploads within your assigned area(s).')
        return redirect('documents:repository')

    if request.method == 'POST':
        form = DocumentEditForm(request.POST, instance=doc)
        if form.is_valid():
            doc = form.save()
            ActivityLog.objects.create(
                user=request.user,
                action='edit_document',
                description=f'Edited metadata for: {doc.title}'
            )
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': f'Document "{doc.title}" updated successfully.',
                    'document': {
                        'id': doc.pk,
                        'title': doc.title,
                        'year': doc.year,
                        'document_type': doc.document_type,
                    },
                })
            messages.success(request, f'Document "{doc.title}" updated successfully.')
            return redirect('documents:repository')
        if is_ajax:
            html = render_to_string(
                'documents/edit_panel.html',
                {'form': form, 'document': doc},
                request=request,
            )
            return HttpResponse(html, status=400)
    else:
        form = DocumentEditForm(instance=doc)

    if is_panel:
        return render(request, 'documents/edit_panel.html', {'form': form, 'document': doc})
    return render(request, 'documents/edit.html', {'form': form, 'document': doc})


@login_required
@repository_access_required
def document_delete(request, pk):
    """Delete a document (Admin & QA Head: any; Faculty: their own uploads in their area only)."""
    try:
        doc = Document.objects.get(pk=pk)
    except Document.DoesNotExist:
        messages.warning(
            request,
            'That document is not in the repository anymore. It may have already been deleted, '
            'or the list you used was out of date — refresh the repository and try again.',
        )
        return redirect('documents:repository')
    if not user_can_modify_document(request.user, doc):
        messages.error(request, 'You can only delete your own uploads within your assigned area(s).')
        return redirect('documents:repository')
    if request.method == 'POST':
        from .ai_pipeline import forget_deleted_matches

        title = doc.title
        deleted_pk = doc.pk
        older_pk = doc.previous_version_id
        # Delete file from storage
        if doc.file and os.path.exists(doc.file.path):
            os.remove(doc.file.path)
        doc.delete()
        forget_deleted_matches([deleted_pk])
        _restore_orphaned_version(older_pk, request.user)
        ActivityLog.objects.create(
            user=request.user,
            action='delete_document',
            description=f'Deleted document: {title}'
        )
        messages.success(request, f'Document "{title}" deleted successfully.')
        return redirect('documents:repository')
    return render(request, 'documents/confirm_delete.html', {'document': doc})


@login_required
@qa_staff_required
def documents_bulk_delete(request):
    """Delete multiple documents from the repository in one action (Admin & QA Head)."""
    if request.method != 'POST':
        return redirect('documents:repository')

    raw_ids = request.POST.getlist('document_ids')
    ids = []
    for val in raw_ids:
        try:
            ids.append(int(val))
        except (TypeError, ValueError):
            continue

    if not ids:
        messages.warning(request, 'No documents were selected for deletion.')
        return redirect('documents:repository')

    docs = list(Document.objects.filter(pk__in=ids))
    if not docs:
        messages.warning(request, 'Selected documents were not found. Refresh and try again.')
        return redirect('documents:repository')

    from .ai_pipeline import forget_deleted_matches

    deleted_count = 0
    deleted_ids = []
    older_pks = []
    for doc in docs:
        # Delete file from storage if present.
        if doc.file and os.path.exists(doc.file.path):
            os.remove(doc.file.path)
        title = doc.title
        deleted_ids.append(doc.pk)
        older_pks.append(doc.previous_version_id)
        doc.delete()
        deleted_count += 1
        ActivityLog.objects.create(
            user=request.user,
            action='delete_document',
            description=f'Deleted document: {title}',
        )
    forget_deleted_matches(deleted_ids)
    for older_pk in older_pks:
        if older_pk not in deleted_ids:
            _restore_orphaned_version(older_pk, request.user)

    messages.success(request, f'Deleted {deleted_count} document(s) successfully.')
    return redirect('documents:repository')


@login_required
@repository_access_required
def document_view(request, pk):
    """View document content inline in the browser — Google Drive style."""
    from .preview_service import uses_pdf_preview, build_pdf_preview, prefer_docx_js_preview

    doc = get_object_or_404(Document, pk=pk)
    if not user_can_access_document(request.user, doc):
        messages.error(request, 'That document is outside your assigned area(s).')
        return redirect('documents:repository')

    preview_mode = 'unsupported'
    rendered_html = ''

    if doc.file_type == 'pdf':
        preview_mode = 'pdf'
    elif uses_pdf_preview(doc.file_type):
        if prefer_docx_js_preview():
            preview_mode = 'docx_js'
        else:
            try:
                build_pdf_preview(doc)
                preview_mode = 'pdf'
            except Exception as exc:
                logger.warning('PDF preview unavailable for document #%s: %s', doc.pk, exc)
                preview_mode = 'docx_js'
    elif doc.file_type == 'xlsx' and doc.file and os.path.exists(doc.file.path):
        from .file_converter import xlsx_to_html
        rendered_html = xlsx_to_html(doc.file.path)
        preview_mode = 'html'
    elif doc.file_type in ('jpg', 'jpeg', 'png'):
        preview_mode = 'image'

    context = {
        'document': doc,
        'preview_mode': preview_mode,
        'rendered_html': rendered_html,
        'embed': request.GET.get('embed') == '1',
        'preview_pdf_path': (
            f'/documents/{doc.pk}/preview/' if preview_mode == 'pdf' and doc.file_type != 'pdf'
            else (f'/documents/{doc.pk}/serve/' if preview_mode == 'pdf' else '')
        ),
    }

    ActivityLog.objects.create(
        user=request.user,
        action='view_document',
        description=f'Viewed file: {doc.title}'
    )

    return render(request, 'documents/view_file.html', context)


@login_required
@repository_access_required
@xframe_options_sameorigin
def document_preview(request, pk):
    """Serve a faithful PDF preview (DOCX → PDF) for in-browser viewing."""
    from .preview_service import uses_pdf_preview, build_pdf_preview

    doc = get_object_or_404(Document, pk=pk)
    if not user_can_access_document(request.user, doc):
        raise Http404('Preview not available.')
    if doc.file_type == 'pdf':
        return document_serve(request, pk)
    if not uses_pdf_preview(doc.file_type):
        raise Http404('Preview not available for this file type.')
    try:
        preview_path = build_pdf_preview(doc)
    except Exception as exc:
        logger.error('Preview generation failed for document #%s: %s', doc.pk, exc)
        raise Http404('Could not generate preview for this document.') from exc

    try:
        fh = open(preview_path, 'rb')
    except OSError as exc:
        raise Http404('Preview file not found.') from exc

    response = FileResponse(fh, content_type='application/pdf')
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=False,
        filename=f'{doc.title or "document"}.pdf',
    )
    return response


@login_required
@repository_access_required
@xframe_options_sameorigin
def document_serve(request, pk):
    """Serve the file for inline viewing (no download header)."""
    doc = get_object_or_404(Document, pk=pk)
    if not user_can_access_document(request.user, doc):
        raise Http404("File not found.")
    if not doc.file:
        raise Http404("File not found.")
    try:
        fh = doc.file.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404("File not found.")

    mime_types = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
    }
    content_type = mime_types.get(doc.file_type, 'application/octet-stream')
    response = FileResponse(fh, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=False,
        filename=doc.filename or 'file',
    )
    return response



# --------------------------------------------------------------------------- #
# Document groups (QA programmes)
#
# The Repository holds everything at once and is filtered down. That is the
# right tool for a search, and the wrong one for "show me the accreditation
# file". These two pages give each programme a place of its own: a list of the
# groups with what is in them, and one page per group.
# --------------------------------------------------------------------------- #

@login_required
@repository_access_required
def document_groups(request):
    """Every QA programme with what it holds, for the viewer's own scope."""
    from django.db.models import Count, Max
    from qa_mapping.models import QAProgram

    docs = scope_documents_for_user(Document.objects.filter(is_archived=False), request.user)

    counts = {
        row['program_id']: row
        for row in docs.values('program_id').annotate(
            files=Count('id'), last_upload=Max('uploaded_at'),
        )
    }
    review_counts = {
        row['program_id']: row['n']
        for row in docs.filter(duplicate_status__in=DUPLICATE_REVIEW_STATUSES)
        .values('program_id').annotate(n=Count('id'))
    }
    pending_counts = {
        row['program_id']: row['n']
        for row in docs.filter(is_processed=False).values('program_id').annotate(n=Count('id'))
    }

    groups = []
    for program in QAProgram.objects.filter(is_active=True).order_by('name'):
        row = counts.get(program.pk, {})
        groups.append({
            'program': program,
            'files': row.get('files', 0),
            'last_upload': row.get('last_upload'),
            'needs_review': review_counts.get(program.pk, 0),
            'pending': pending_counts.get(program.pk, 0),
        })

    unassigned = counts.get(None, {})
    return render(request, 'documents/document_groups.html', {
        'groups': groups,
        'unassigned_files': unassigned.get('files', 0),
        'unassigned_last_upload': unassigned.get('last_upload'),
        'total_files': docs.count(),
    })


@login_required
@repository_access_required
def document_group_detail(request, code):
    """The documents of one QA programme, or of no programme at all."""
    from qa_mapping.models import QAProgram

    docs = scope_documents_for_user(
        Document.objects.filter(is_archived=False), request.user,
    ).select_related('uploaded_by', 'uploaded_by__profile', 'acc_area', 'program')

    if code == 'unassigned':
        program = None
        docs = docs.filter(program__isnull=True)
        heading, subtitle = 'No category', 'Documents that have not been filed under a QA programme'
    else:
        program = get_object_or_404(QAProgram, code__iexact=code)
        docs = docs.filter(program=program)
        heading, subtitle = program.name, program.description or f'Documents filed under {program.code}'

    docs = docs.order_by('-uploaded_at')
    return render(request, 'documents/document_group_detail.html', {
        'program': program,
        'group_code': code,
        'heading': heading,
        'subtitle': subtitle,
        'documents': docs,
        'total_count': docs.count(),
        'needs_review_count': docs.filter(duplicate_status__in=DUPLICATE_REVIEW_STATUSES).count(),
        'pending_count': docs.filter(is_processed=False).count(),
        'cluster_names': _cluster_names(),
    })

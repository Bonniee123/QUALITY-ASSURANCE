"""
Full and light AI processing pipelines for documents.
Used after upload and from the AI Processing admin UI.
"""
import logging

import os
import threading

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# One full run at a time, whoever asks: the upload worker, the AI Processing
# page, a single-file upload. Each run rewrites every cluster label and clears
# and rebuilds ClusterResult, so two overlapping runs interleaved those writes
# and the survivor depended on which finished last.
_RUN_LOCK = threading.Lock()


def run_full_ai_pipeline(request):
    """
    Run TF-IDF, Elbow, K-Means, duplicate detection, and recommendations on ALL documents.
    """
    with _RUN_LOCK:
        return _run_full_ai_pipeline(request)


def _run_full_ai_pipeline(request):
    from ai_processing.cluster_features import build_clustering_matrix
    from ai_processing.clustering_text import clustering_input_text
    from ai_processing.smart_clustering import run_smart_clustering
    from ai_processing.tfidf_service import compute_tfidf_keywords
    from ai_processing.duplicate_checker import check_all_duplicates
    from ai_processing.recommendation_service import generate_document_recommendation
    from documents.models import Document, ClusterResult

    # Current documents only. Archived versions are hidden everywhere else --
    # Repository, Dashboard, Reports, the upload checks -- and used to be
    # clustered and duplicate-matched here, so a cluster or a "Needs review"
    # could rest on a document nobody could open. What earlier runs gave them is
    # cleared, since it no longer describes anything on screen.
    Document.objects.filter(is_archived=True).exclude(cluster_label__isnull=True).update(cluster_label=None)
    Document.objects.filter(is_archived=True).exclude(duplicate_status='none').update(
        duplicate_status='none', similar_documents=[])
    documents = Document.objects.filter(is_archived=False)
    n = documents.count()
    if n == 0:
        return 'No documents in repository.'
    if n < 2:
        if n == 1:
            doc = documents.first()
            if doc.combined_text:
                _tfidf_matrix, _feature_names, keywords_per_doc = compute_tfidf_keywords(
                    [doc.combined_text or doc.title]
                )
                if keywords_per_doc:
                    doc.tfidf_keywords = keywords_per_doc[0]
                    doc.is_processed = True
                    doc.save(update_fields=['tfidf_keywords', 'is_processed'])
        return 'Keywords extracted (need 2+ documents for clustering)'

    doc_list = list(documents)
    texts = [doc.combined_text or doc.title for doc in doc_list]

    tfidf_matrix, feature_names, keywords_per_doc = compute_tfidf_keywords(texts)
    if tfidf_matrix is None:
        # Too little text to vectorise -- an archive of diagrams and screenshots
        # reaches this easily ("after pruning, no terms remain"). The pipeline
        # used to stop here, which meant an image-heavy corpus got no duplicate
        # detection of any kind and every document was left on "Checking…".
        # Comparing images does not need text, so that work still runs.
        return _finish_without_text(doc_list, 'not enough text to compare')

    for i, doc in enumerate(doc_list):
        if i < len(keywords_per_doc):
            doc.tfidf_keywords = keywords_per_doc[i]
            doc.is_processed = True
            doc.save(update_fields=['tfidf_keywords', 'is_processed'])

    cluster_texts = [clustering_input_text(doc) for doc in doc_list]
    cluster_matrix, cluster_features, cluster_backend = build_clustering_matrix(doc_list, cluster_texts)
    if cluster_matrix is None:
        return _finish_without_text(doc_list, 'not enough text to cluster')

    smart = _cluster_single_threaded(run_smart_clustering, doc_list, cluster_matrix, cluster_features)
    optimal_k = smart['total_clusters']
    backend_note = cluster_backend if cluster_backend else 'tfidf'

    if request and smart.get('elbow_summary'):
        request.session['elbow_data'] = smart['elbow_summary']
    if request:
        request.session['ai_cluster_backend'] = backend_note
        from django.utils import timezone
        request.session['ai_last_pipeline_at'] = timezone.now().isoformat()
        request.session['ai_last_pipeline_message'] = (
            f'{len(doc_list)} documents → {optimal_k} clusters ({backend_note})'
        )

    if smart['labels']:
        ClusterResult.objects.all().delete()
        for i, doc in enumerate(doc_list):
            if i >= len(smart['labels']):
                continue
            label = smart['labels'][i]
            meta = smart['cluster_meta'].get(label, {})
            doc.cluster_label = label
            doc.is_processed = True
            doc.save(update_fields=['cluster_label', 'is_processed'])

            top_terms = meta.get('top_terms') or []
            display_label = meta.get('display_label') or f'Cluster {label}'
            ClusterResult.objects.create(
                document=doc,
                cluster_number=label,
                cluster_label=display_label,
                top_keywords=top_terms,
            )
        _record_clustering_method(backend_note, len(doc_list), smart.get('elbow_summary'))

    duplicates_map = check_all_duplicates(tfidf_matrix)
    new_duplicate_alerts = []
    # Every document that was compared gets a verdict, including a clean one.
    #
    # This used to iterate `duplicates_map`, which `check_all_duplicates` only
    # populates for documents that *have* a match ("if duplicates: result[i] =
    # ..."). A document checked and found clean was therefore never visited, so
    # it kept the 'pending_check' it was created with -- and the repository
    # renders that as "Checking…". The check had finished; nothing ever wrote
    # down that it had passed, so the column hung forever on exactly the
    # documents with nothing wrong with them.
    #
    # A text verdict is only trusted where the text is the document. An image is
    # judged by its pixels a few lines below, in _apply_visual_duplicates, and
    # any file with too little text to characterise is left to the exact-hash
    # and visual checks rather than to cosine similarity over a handful of terms.
    #
    # Archived documents -- older versions, hidden everywhere else -- are left
    # out of the comparison on both sides. They used to take part, so a current
    # document could be sent for review against a match nobody could open.
    from ai_processing.image_hash import is_image_file

    min_text = int(getattr(settings, 'DUPLICATE_TEXT_MIN_CHARS', 400))
    # Each document as it stood before this run: staff decisions are kept on
    # its matches, and an alert is owed only for a pair it did not list yet.
    before = _duplicate_snapshot(doc_list)
    visual = _visual_matches(doc_list)
    frequencies = {}

    for doc_idx, doc in enumerate(doc_list):
        text_len = len((doc.combined_text or '').strip())
        trust_text = (not doc.is_archived and not is_image_file(doc.file_type)
                      and text_len >= min_text)
        dups = duplicates_map.get(doc_idx, []) if trust_text else []
        similar_ids = verified_text_matches(doc, dups, doc_list, frequencies)
        if visual.get(doc.pk):
            similar_ids, _changed = merge_visual_matches(similar_ids, visual[doc.pk])
        new_ids = settle_duplicate_verdict(doc, similar_ids, *before[doc.pk])
        if new_ids:
            new_duplicate_alerts.append((doc, doc.similar_documents, new_ids))

    _notify_duplicate_alerts(new_duplicate_alerts)

    for doc in doc_list:
        cluster_docs = Document.objects.filter(cluster_label=doc.cluster_label)
        doc.recommendation = generate_document_recommendation(doc, cluster_docs)
        doc.save(update_fields=['recommendation'])

    return (
        f'AI processing complete — {len(doc_list)} documents clustered into '
        f'{optimal_k} groups (smart clustering, {backend_note})'
    )


# Each run that relabels the clusters records what it clustered with, so the AI
# result page can say how the clusters on screen were made. A run after an upload
# happens in the background, with no page session to write to, and the badge fell
# back to the settings -- "Semantic embeddings" even for a run that had used
# TF-IDF because the PC was short of memory.
CLUSTERING_RUN_METRIC = 'clustering_run'
CLUSTERING_METHODS = ('embedding', 'hybrid', 'tfidf')


def _record_clustering_method(backend, document_count, elbow_summary=None):
    from documents.models import ProcessingMetric

    meta = {'backend': backend}
    # The Elbow chart used to live only in the session of the person whose page
    # ran the pipeline in the foreground; with background jobs (the default)
    # nobody saw it, and a second Admin never did. It is kept with the run.
    if elbow_summary and elbow_summary.get('k_values'):
        meta['elbow'] = elbow_summary
    try:
        ProcessingMetric.objects.create(
            metric_name=CLUSTERING_RUN_METRIC,
            metric_value=float(document_count),
            unit='documents',
            meta=meta,
        )
    except Exception:
        # Only the badge and the Elbow chart depend on this; the clusters themselves are saved.
        logger.exception('Could not record which method this clustering run used')


def last_clustering_method():
    """What the latest clustering run used -- 'embedding', 'hybrid' or 'tfidf' -- or '' if none is recorded."""
    from documents.models import ProcessingMetric

    meta = (
        ProcessingMetric.objects.filter(metric_name=CLUSTERING_RUN_METRIC)
        .order_by('-created_at', '-pk')
        .values_list('meta', flat=True)
        .first()
    )
    backend = meta.get('backend') if isinstance(meta, dict) else ''
    return backend if backend in CLUSTERING_METHODS else ''


def last_elbow_summary():
    """The Elbow result of the latest clustering run that produced one, or None."""
    from documents.models import ProcessingMetric

    meta = (
        ProcessingMetric.objects.filter(metric_name=CLUSTERING_RUN_METRIC)
        .order_by('-created_at', '-pk')
        .values_list('meta', flat=True)
        .first()
    )
    elbow = meta.get('elbow') if isinstance(meta, dict) else None
    return elbow if isinstance(elbow, dict) and elbow.get('k_values') else None


def _cluster_single_threaded(run, *args):
    """
    Run clustering with its native thread pools held to one thread.

    Clustering fits K-Means for every k from 2 to 8 in each area/type group --
    57 fits on this corpus, on groups of about 16 documents. At that size the
    work is microseconds; nearly all of each fit's 53 ms was the OpenMP/BLAS pool
    starting its threads. With one thread the same step measures 0.67 s instead
    of 3.5 s, and the cluster labels come out identical.
    """
    try:
        from threadpoolctl import threadpool_limits
    except Exception:  # pragma: no cover - ships with scikit-learn
        return run(*args)
    with threadpool_limits(limits=1):
        return run(*args)


def run_light_post_upload(request, new_documents):
    """
    For large corpora: update TF-IDF keywords only for newly uploaded documents.
    Skips global clustering/duplicates — staff should run full AI from the AI Processing page.
    """
    from ai_processing.tfidf_service import compute_tfidf_keywords
    from documents.models import Document

    if not new_documents:
        return 'No new documents to process.'

    doc_list = list(new_documents)
    for doc in doc_list:
        doc.refresh_from_db()
        text = (doc.combined_text or doc.title or '').strip()
        if text:
            _m, _fn, keywords_per_doc = compute_tfidf_keywords([text])
            if keywords_per_doc:
                doc.tfidf_keywords = keywords_per_doc[0]
                if doc.duplicate_status == 'none':
                    doc.duplicate_status = 'pending_check'
                    doc.is_processed = True
                    doc.save(update_fields=['tfidf_keywords', 'duplicate_status', 'is_processed'])
                else:
                    doc.is_processed = True
                    doc.save(update_fields=['tfidf_keywords', 'is_processed'])
            else:
                doc.is_processed = True
                doc.save(update_fields=['is_processed'])
        else:
            doc.is_processed = True
            doc.save(update_fields=['is_processed'])

    n = len(doc_list)
    total = Document.objects.count()
    max_full = getattr(settings, 'AI_AUTO_FULL_PIPELINE_MAX_DOCS', 75)
    return (
        f'Keywords updated for {n} new file(s). Repository has {total} documents '
        f'(over auto full-pipeline limit of {max_full}). '
        f'Use AI Processing → Run AI processing to refresh clusters, duplicates, and recommendations.'
    )


def verified_text_matches(doc, candidates, doc_list, frequencies=None):
    """
    The text candidates that still agree once the two documents are compared as
    they are written.

    The TF-IDF matrix that proposes a candidate is built from `clean_text`,
    which deletes every standalone number. That suits clustering, but it means
    a set of generated reports whose only differences *are* numbers collapses
    onto one another: three "Dashboard Summary" exports in this archive,
    reporting 22, 18 and 16 documents on three different dates, scored exactly
    1.0000 against each other and were shown to the reader as an all-but-perfect
    match. The same stripping understates real pairs, because a manuscript and
    its PDF lose the figures, dates and numbering they share.

    So every candidate is measured again here, over the full text of just those
    two documents, and it has to clear the same configured threshold a second
    time to be recorded. The number stored is the one from this second measure,
    which is the one a reader can check against the files.

    ``frequencies`` is an optional cache, keyed by primary key, so a document's
    word counts are built once per run.

    Returns match dicts, highest agreement first.
    """
    from ai_processing.duplicate_checker import (
        duplicate_threshold, frequency_agreement, word_frequencies,
    )

    cache = {} if frequencies is None else frequencies

    def counts(document):
        if document.pk not in cache:
            cache[document.pk] = word_frequencies(document.combined_text)
        return cache[document.pk]

    threshold = duplicate_threshold()
    matches = []
    for candidate in candidates:
        index = candidate.get('index')
        if index is None or not (0 <= index < len(doc_list)):
            continue
        other = doc_list[index]
        if other.is_archived or other.pk == doc.pk:
            continue
        agreement = frequency_agreement(counts(doc), counts(other))
        if agreement < threshold:
            continue
        matches.append({
            'id': other.pk,
            'title': other.title,
            'similarity': round(agreement, 4),
            'match_type': 'text',
        })
    matches.sort(key=lambda m: m['similarity'], reverse=True)
    return matches


def merge_visual_matches(similar_documents, visual_matches):
    """
    Merge perceptual-hash visual matches into an existing similar_documents list.

    - Existing text matches are tagged with match_type='text' (when untagged).
    - Visual matches that reference a new document id are appended (match_type='visual').
    - The result is sorted by similarity (highest first).
    Returns (merged_list, changed_bool).
    """
    existing = [dict(m) for m in (similar_documents or [])]
    changed = False
    for m in existing:
        if 'match_type' not in m:
            m['match_type'] = 'text'
            changed = True
    existing_ids = {m.get('id') for m in existing}
    for vm in visual_matches:
        if vm['id'] not in existing_ids:
            existing.append(vm)
            existing_ids.add(vm['id'])
            changed = True
    if changed:
        existing.sort(key=lambda x: x.get('similarity', 0), reverse=True)
    return existing, changed


def _finish_without_text(doc_list, reason):
    """
    Close out a run that could not use text, without leaving anything hanging.

    Two things still have to happen even when there is no usable text. Images
    can be compared by their pixels, which is the better test for them anyway.
    And every document needs a duplicate verdict recorded: a document left on
    'pending_check' shows as "Checking…" in the repository for ever, which is
    indistinguishable from the check having crashed.
    """
    before = _duplicate_snapshot(doc_list)
    for doc in doc_list:
        if doc.duplicate_status == 'pending_check':
            doc.duplicate_status = 'none'
            doc.is_processed = True
            doc.save(update_fields=['duplicate_status', 'is_processed'])

    alerts = _apply_visual_duplicates(doc_list, before)
    if alerts:
        _notify_duplicate_alerts(alerts)
    flagged = len(alerts)
    return (
        f'{len(doc_list)} document(s) processed — {reason}. '
        f'Compared images by appearance instead'
        + (f'; {flagged} flagged for review.' if flagged else '; none matched.')
    )


def _name_stem_ratio(doc_a, doc_b):
    """
    How alike two uploads' file names are once version noise is removed.

    "figure2-document-ai-flowchart.png" and "figure2-document-ai-flowchart_1.png"
    are the same figure saved twice; the trailing counter, the extension and any
    ".draw" from a diagram export carry no meaning here.
    """
    import difflib
    import re

    def stem(doc):
        name = os.path.basename((doc.file.name or '') if doc.file else '') or (doc.title or '')
        name = re.sub(r'\.[A-Za-z0-9]+$', '', name)          # extension
        name = re.sub(r'\.(draw|drawio)$', '', name, flags=re.I)
        name = re.sub(r'[._\s-]*(?:\(\d+\)|\d+)$', '', name)  # _1, (2), trailing digits
        return re.sub(r'[^a-z0-9]+', '', name.lower())

    a, b = stem(doc_a), stem(doc_b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _duplicate_snapshot(doc_list):
    """Each document's duplicate status and match list as they stand now, by id."""
    return {
        doc.pk: (doc.duplicate_status,
                 [dict(m) for m in (doc.similar_documents or []) if isinstance(m, dict)])
        for doc in doc_list
    }


REVIEW_CONFIRMED = 'confirmed'
REVIEW_DISMISSED = 'dismissed'


def _pair_reviews(status, matches):
    """The staff decision on each listed match, by matched document id."""
    reviews = {m.get('id'): m['review'] for m in matches
               if m.get('review') in (REVIEW_CONFIRMED, REVIEW_DISMISSED)}
    if not reviews and matches:
        # Decided before decisions were kept per match: a confirmed document
        # confirmed its whole list, and a dismissal cleared the status but kept
        # the list -- nothing else leaves a list behind a 'none'.
        if status == 'confirmed_dup':
            reviews = {m.get('id'): REVIEW_CONFIRMED for m in matches}
        elif status == 'none':
            reviews = {m.get('id'): REVIEW_DISMISSED for m in matches}
    return reviews


def settle_duplicate_verdict(doc, matches, before_status, before_matches):
    """
    Record this run's matches as the document's duplicate verdict, keeping the
    decisions staff already made on them.

    A Confirm or Dismiss belongs to the matches it was made on, and stays with
    each of them while it still matches; re-processing used to overwrite both --
    a confirmed duplicate went back to "Needs review", and a dismissed one was
    flagged again and re-announced to its uploader and every staff member. The
    status follows from the matches: any not yet reviewed -> 'possible';
    otherwise any confirmed -> 'confirmed_dup'; otherwise 'none'.

    Saves only if something changed. Returns the ids of matches that are new
    since the last run and await a decision -- the only ones worth an alert.
    """
    reviews = _pair_reviews(before_status, before_matches or [])
    settled = []
    for match in matches:
        match = {k: v for k, v in match.items() if k != 'review'}
        if match.get('id') in reviews:
            match['review'] = reviews[match['id']]
        settled.append(match)

    open_ids = [m.get('id') for m in settled if not m.get('review')]
    if open_ids:
        status = 'possible'
    elif any(m.get('review') == REVIEW_CONFIRMED for m in settled):
        status = 'confirmed_dup'
    else:
        status = 'none'

    if status != doc.duplicate_status or settled != (doc.similar_documents or []):
        doc.duplicate_status = status
        doc.similar_documents = settled
        doc.save(update_fields=['duplicate_status', 'similar_documents'])

    listed_before = {m.get('id') for m in before_matches or []}
    return [pk for pk in open_ids if pk not in listed_before]


def record_duplicate_review(doc, decision):
    """Confirm or dismiss every match the document lists now (REVIEW_CONFIRMED / REVIEW_DISMISSED)."""
    # When, as well as what. The decision was recorded without a date, so the
    # panel could say a match had been reviewed but not when -- which is the
    # first thing anyone auditing the archive asks of a decision.
    stamped = timezone.now().isoformat()
    doc.similar_documents = [dict(m, review=decision, reviewed_at=stamped)
                             for m in (doc.similar_documents or []) if isinstance(m, dict)]
    doc.duplicate_status = 'confirmed_dup' if decision == REVIEW_CONFIRMED else 'none'
    doc.save(update_fields=['duplicate_status', 'similar_documents'])


def forget_deleted_matches(deleted_ids):
    """
    Take deleted documents out of the match lists that name them.

    A document flagged against one that was then deleted stayed on "Needs
    review", with an empty list, until the next full run. Returns how many
    documents changed.
    """
    from documents.models import Document

    gone = {pk for pk in deleted_ids if pk is not None}
    if not gone:
        return 0
    changed = 0
    for doc in Document.objects.only('pk', 'duplicate_status', 'similar_documents', 'content_sha256'):
        matches = [m for m in (doc.similar_documents or []) if isinstance(m, dict)]
        kept = [m for m in matches if m.get('id') not in gone]
        if len(kept) != len(matches):
            settle_duplicate_verdict(doc, kept, doc.duplicate_status, matches)
            changed += 1
    return changed


def _visual_matches(doc_list):
    """
    Each image's visually similar images in doc_list, by document id.

    Archived versions are left out, as in the text comparison.
    """
    from ai_processing.image_hash import (
        VERDICT_DIFFERENT, VERDICT_DUPLICATE, compare_matrices, hamming_distance,
        is_image_file, load_image_matrix, max_distance, pixel_verdict, visual_similarity,
    )

    image_docs = [d for d in doc_list
                  if is_image_file(d.file_type) and d.image_phash and not d.is_archived]
    if len(image_docs) < 2:
        return {}

    cutoff = max_distance()
    review_cutoff = int(getattr(settings, 'IMAGE_PHASH_REVIEW_DISTANCE', 10))
    name_ratio = float(getattr(settings, 'IMAGE_NAME_MATCH_RATIO', 0.85))

    # The hash narrows the field; the pixels give the verdict and the number.
    # A 64-bit gradient signature reports bit agreement, not picture agreement:
    # two tutorial flowcharts that share a file-name stem scored "88% similar"
    # while a quarter of the picture differed. Each image is read once here and
    # compared properly. When a file cannot be read -- it has been moved, or the
    # row predates the file -- the older hash-and-name rules still decide, so
    # nothing silently stops being checked.
    matrices = {}

    def matrix_for(doc):
        if doc.pk not in matrices:
            try:
                matrices[doc.pk] = load_image_matrix(doc.file.path)
            except (ValueError, OSError):
                matrices[doc.pk] = None
        return matrices[doc.pk]

    found = {}
    for doc in image_docs:
        visual_matches = []
        for other in image_docs:
            if other.pk == doc.pk:
                continue
            dist = hamming_distance(doc.image_phash, other.image_phash)
            if dist is None or dist > max(cutoff, review_cutoff):
                continue
            share, mean = compare_matrices(matrix_for(doc), matrix_for(other))
            if mean is None:
                # No readable pixels: fall back to hash distance, with the file
                # name breaking the tie inside the review band as it always has.
                if dist > cutoff and _name_stem_ratio(doc, other) < name_ratio:
                    continue
                similarity = round(visual_similarity(doc.image_phash, other.image_phash) or 0.0, 4)
                match_type = 'visual' if dist <= cutoff else 'visual_named'
            else:
                verdict = pixel_verdict(mean)
                if verdict == VERDICT_DIFFERENT:
                    continue
                # What a reader can check for themselves: the share of the
                # picture that matches, not a hash's bit agreement.
                similarity = round(share, 4) if share is not None else 0.0
                match_type = 'visual' if verdict == VERDICT_DUPLICATE else 'visual_review'
            visual_matches.append({
                'id': other.pk,
                'title': other.title,
                'similarity': similarity,
                'match_type': match_type,
            })
        if visual_matches:
            found[doc.pk] = visual_matches
    return found


def _apply_visual_duplicates(doc_list, before=None):
    """
    Record each image's visual matches as its duplicate verdict -- the whole
    verdict, since an image is never judged on its OCR text. Returns
    (doc, similar_documents, new_ids) alerts for pairs new since the last run.
    """
    from ai_processing.image_hash import is_image_file

    if before is None:
        before = _duplicate_snapshot(doc_list)
    visual = _visual_matches(doc_list)
    alerts = []
    for doc in doc_list:
        if not (is_image_file(doc.file_type) and doc.image_phash):
            continue
        matches = merge_visual_matches([], visual[doc.pk])[0] if visual.get(doc.pk) else []
        new_ids = settle_duplicate_verdict(doc, matches, *before[doc.pk])
        if new_ids:
            alerts.append((doc, doc.similar_documents, new_ids))
    return alerts


def _notify_duplicate_alerts(alerts):
    """
    Tell the uploader and QA staff once about each newly found pair.

    Alerts are (doc, similar_documents, new_ids). Both documents of a new pair
    are flagged in the same run, and each used to send its own alert; the first
    one listed -- the newer upload -- now speaks for the pair. Pairs already
    listed before the run are not announced again (they were, on every run).
    """
    if not alerts:
        return
    try:
        from django.urls import reverse

        from notifications.services import notify, notify_qa_staff
        from notifications.user_messages import duplicate_detected_message
    except Exception:
        return
    announced = set()
    for doc, similar, new_ids in alerts:
        pairs = {frozenset((doc.pk, other)) for other in new_ids}
        if pairs and pairs <= announced:
            continue
        announced |= pairs
        try:
            link = reverse('documents:detail', args=[doc.pk])
        except Exception:
            link = ''
        msg = duplicate_detected_message(doc.title, len(similar))
        if doc.uploaded_by_id and not _receives_staff_alerts(doc.uploaded_by):
            notify(doc.uploaded_by, msg, category='duplicate', link=link)
        notify_qa_staff(msg, category='duplicate', link=link)


def _receives_staff_alerts(user):
    """True if notify_qa_staff already reaches this user (so they are not told twice)."""
    profile = getattr(user, 'profile', None)
    return bool(user.is_active and profile is not None and profile.role in ('admin', 'qa_staff')
                and profile.status == 'active')

"""
Smart search service for documents.
Searches across metadata, extracted text, keywords, and more.
"""
import re

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from documents.models import Document


def _tokens(text):
    return {t for t in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(t) > 1}


# Punctuation that ends a word in a sentence rather than belonging to it.
_EDGE_PUNCTUATION = '.,;:!?()[]{}"\''


def _word_variants(word):
    """
    The spellings of a search word that should find it.

    Words are matched as substrings, so "report" already finds "reports". What
    a substring cannot bridge is the other direction and the "y"/"ies" change:
    "reports" must find "report", "policies" "policy", and "policy" "policies".
    """
    variants = [word]
    if not word.isalpha() or len(word) <= 3:
        return variants
    if word.endswith('ies'):
        variants.append(word[:-3] + 'y')
    elif word.endswith(('sses', 'xes', 'zes', 'ches', 'shes')):
        variants.append(word[:-2])
    elif word.endswith('s') and not word.endswith('ss'):
        variants.append(word[:-1])
    elif word.endswith('y') and word[-2] not in 'aeiou':
        variants.append(word[:-1] + 'ies')
    return variants


def query_terms(query):
    """
    The words of a search, each as the list of spellings that should match it.

    Searching used to look for the whole query as one unbroken phrase, so
    "policy enrollment" missed a document about an "enrollment policy", a phrase
    broken across two lines was missed, and "policies" missed "policy".
    """
    terms = []
    for raw in (query or '').lower().split():
        word = raw.strip(_EDGE_PUNCTUATION) or raw
        terms.append(_word_variants(word))
    return terms


def _is_keyword_term(word):
    """
    True if a word can be looked up in the stored keywords.

    tfidf_keywords is stored as JSON pairs -- [["policy", 0.2572], ...] -- and
    searching its text found "0.4" in the scores and '"' in the punctuation,
    so a number or a quote matched nearly every document. Only a word with a
    letter in it, and nothing but letters and digits, is matched against it.
    """
    return word.isalnum() and any(ch.isalpha() for ch in word)


def _term_q(variants):
    """Any field of a document contains one of these spellings."""
    q = Q()
    for word in variants:
        q |= (
            Q(title__icontains=word) |
            Q(description__icontains=word) |
            Q(extracted_text__icontains=word) |
            Q(ocr_text__icontains=word) |
            Q(qa_area__icontains=word) |
            Q(criterion__icontains=word) |
            Q(indicator__icontains=word) |
            Q(document_type__icontains=word) |
            Q(file_type__icontains=word) |
            Q(acc_area__area_code__icontains=word)
        )
        if _is_keyword_term(word):
            q |= Q(tfidf_keywords__icontains=word)
    return q


def _hybrid_score(query, doc):
    query_l = (query or '').lower().strip()
    q_tokens = _tokens(query_l)
    if not q_tokens:
        return 0.0

    title = (doc.title or '').lower()
    desc = (doc.description or '').lower()
    main_text = f'{doc.extracted_text or ""} {doc.ocr_text or ""}'.lower()
    tfidf_raw = doc.tfidf_keywords
    if isinstance(tfidf_raw, list):
        tfidf_text = ' '.join(str(x) for x in tfidf_raw if x)
    else:
        tfidf_text = str(tfidf_raw or '')
    tfidf_text = tfidf_text.lower()
    tags = ' '.join([
        doc.document_type or '',
        doc.qa_area or '',
        doc.criterion or '',
        doc.indicator or '',
        getattr(doc.acc_area, 'area_code', '') or '',
    ]).lower()

    fields = [
        (title, 3.0),
        (desc, 1.8),
        (main_text, 1.4),
        (tfidf_text, 2.2),
        (tags, 1.5),
    ]

    score = 0.0
    for text, weight in fields:
        if not text:
            continue
        if query_l and query_l in text:
            score += 6.0 * weight
        t_tokens = _tokens(text)
        if not t_tokens:
            continue
        overlap = len(q_tokens & t_tokens)
        if overlap:
            score += (overlap / max(1, len(q_tokens))) * 10.0 * weight
    return score


def explain_match(query, doc):
    query_l = (query or '').lower().strip()
    if not query_l:
        return []
    reasons = []
    checks = [
        ('title', (doc.title or '')),
        ('description', (doc.description or '')),
        ('ocr text', (doc.ocr_text or '')),
        ('extracted text', (doc.extracted_text or '')),
        ('keywords', ' '.join(str(x) for x in (doc.tfidf_keywords or []))),
        ('document type', (doc.document_type or '')),
        ('QA area', (doc.qa_area or '')),
    ]
    for label, text in checks:
        if query_l and query_l in (text or '').lower():
            reasons.append(label)
    if getattr(doc, 'acc_area', None) and query_l in (getattr(doc.acc_area, 'area_code', '') or '').lower():
        reasons.append('accreditation area')
    dedup = []
    for r in reasons:
        if r not in dedup:
            dedup.append(r)
    return dedup


def _apply_hybrid_rerank(documents, query):
    if not query:
        return documents
    if not bool(getattr(settings, 'ENABLE_HYBRID_SMART_SEARCH', True)):
        return documents

    pool_size = int(getattr(settings, 'HYBRID_SEARCH_CANDIDATE_POOL', 200))
    max_rank = int(getattr(settings, 'HYBRID_SEARCH_MAX_RANKED', 120))
    if pool_size <= 0 or max_rank <= 0:
        return documents

    candidate_docs = list(
        documents.select_related('acc_area')
        .only(
            'id', 'uploaded_at', 'title', 'description', 'extracted_text',
            'ocr_text', 'tfidf_keywords', 'document_type', 'qa_area',
            'criterion', 'indicator', 'acc_area__area_code',
        )
        .order_by('-uploaded_at')[:pool_size]
    )
    if not candidate_docs:
        return documents

    scored = sorted(
        ((doc.pk, _hybrid_score(query, doc)) for doc in candidate_docs),
        key=lambda item: item[1],
        reverse=True,
    )[:max_rank]
    ranked_ids = [pk for pk, score in scored if score > 0]
    if not ranked_ids:
        return documents

    priority = Case(
        *[When(pk=pk, then=idx) for idx, pk in enumerate(ranked_ids)],
        default=Value(len(ranked_ids) + 1),
        output_field=IntegerField(),
    )
    return documents.order_by(priority, '-uploaded_at')


def search_documents(query, filters=None, include_archived=False):
    """
    Search documents using query text and optional filters.

    Args:
        query: Search text
        filters: Dict with optional keys: year, document_type, file_type, duplicate, cluster, qa_area,
        evidence_status, program, acc_area_id
        include_archived: If False (default) hide superseded versions.

    Returns:
        QuerySet of matching documents.
    """
    # Deleted documents never appear, whatever `include_archived` says. That
    # flag chooses whether superseded versions are shown, which is a different
    # question from whether somebody removed the document.
    documents = Document.objects.live()
    if not include_archived:
        documents = documents.filter(is_archived=False)

    if query:
        # Every word must appear, in any order and in any field (its own field
        # may differ from word to word).
        q_filter = Q()
        for variants in query_terms(query):
            q_filter &= _term_q(variants)
        documents = documents.filter(q_filter)

    if filters:
        year_raw = filters.get('year')
        if year_raw:
            try:
                documents = documents.filter(year=int(year_raw))
            except (ValueError, TypeError):
                pass
        if filters.get('document_type'):
            documents = documents.filter(document_type__icontains=filters['document_type'])
        if filters.get('file_type'):
            documents = documents.filter(file_type__iexact=filters['file_type'].strip())
        duplicate_raw = filters.get('duplicate')
        if duplicate_raw == 'review':
            documents = documents.filter(
                duplicate_status__in=('possible', 'pending_check', 'confirmed_dup'),
            )
        elif duplicate_raw in ('possible', 'pending_check', 'confirmed_dup', 'none'):
            documents = documents.filter(duplicate_status=duplicate_raw)
        cluster_raw = filters.get('cluster')
        if cluster_raw is not None and cluster_raw != '':
            try:
                documents = documents.filter(cluster_label=int(cluster_raw))
            except (ValueError, TypeError):
                pass
        if filters.get('qa_area'):
            # The area itself, not every area whose code contains it: "Area I"
            # used to bring in Areas II, III, IV and IX as well.
            from documents.area_utils import build_area_filter_q
            documents = documents.filter(build_area_filter_q([filters['qa_area'].strip()]))
        if filters.get('evidence_status'):
            documents = documents.filter(evidence_status=filters['evidence_status'])
        program_raw = filters.get('program')
        if program_raw:
            try:
                documents = documents.filter(program_id=int(program_raw))
            except (ValueError, TypeError):
                pass
        # Faculty area scoping: restrict to a set of accreditation area codes.
        area_codes = filters.get('area_codes')
        if area_codes:
            from documents.area_utils import build_area_filter_q
            documents = documents.filter(build_area_filter_q(area_codes))
        raw_area = filters.get('acc_area_id')
        if raw_area:
            try:
                documents = documents.filter(acc_area_id=int(raw_area))
            except (ValueError, TypeError):
                pass

    documents = documents.distinct().order_by('-uploaded_at')
    return _apply_hybrid_rerank(documents, query)


def compute_facet_counts(query, filters=None, include_archived=False):
    """
    Compute counts for each facet value, given the current text query and
    every filter EXCEPT the facet itself. This makes counts feel "live" — they
    reflect what would happen if the user picked that value next.

    Returns a dict keyed by facet name with sub-dicts {value: count}.
    """
    facets = ['year', 'document_type', 'cluster', 'evidence_status', 'program']
    counts = {}
    base_filters = {k: v for k, v in (filters or {}).items() if v}

    for facet in facets:
        sibling_filters = {k: v for k, v in base_filters.items() if k != facet}
        qs = search_documents(query, sibling_filters, include_archived=include_archived)
        if facet == 'cluster':
            field_name = 'cluster_label'
        elif facet == 'program':
            field_name = 'program_id'
        else:
            field_name = facet
        per_value = {}
        # Include pk so .distinct() (already in search_documents) doesn't collapse rows by facet value
        for _pk, val in qs.values_list('pk', field_name):
            if val is None or val == '':
                continue
            per_value[val] = per_value.get(val, 0) + 1
        counts[facet] = per_value

    return counts

"""
The QA Archive Agent.

Answers questions about the archive from the archive itself. Every figure, title,
date and classification in a reply is read out of the database through the same
retrieval code the Repository page uses -- ``search.search_service`` -- so the
agent cannot describe a document the system does not hold.

No external API. The intelligence is the system's own: TF-IDF keyword sets and
K-Means cluster assignments already stored on each document, the accreditation
hierarchy, the QA programme records, and the extracted/OCR text.

Design notes
------------
* Retrieval is always scoped by the caller's permissions. A Faculty member asking
  "find accreditation documents" gets only their assigned areas, because the same
  ``faculty_area_scope`` used by the Repository is applied here.
* The agent never invents. Where the records cannot answer, it says so -- see
  ``_no_data`` -- rather than producing a plausible-sounding guess.
* Conversation state lives in the session and holds the *identifiers* of the last
  result set, so "which ones are from 2025?" and "summarize the second one" are
  resolved against real rows rather than against the text of the last reply.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from django.db.models import Count, Q
from django.urls import reverse

from documents.models import ClusterResult, Document
from accounts.permissions import faculty_area_scope, scope_documents_for_user, NO_AREA_SENTINEL

from . import agent_nlu as nlu
from .agent_nlu import Understanding

# Session keys. Kept separate from the legacy chat history so the old rules
# engine and its tests continue to work untouched.
CONTEXT_KEY = 'qa_agent_context'
MAX_TRACKED_RESULTS = 25
# Below this, a match is incidental rather than an intent.
MIN_CONFIDENCE = 4
PAGE_SIZE = 5


# --------------------------------------------------------------------------- #
# Conversation context
# --------------------------------------------------------------------------- #

class AgentContext:
    """
    What the agent remembers between turns.

    Only identifiers are stored, never rendered text: resolving "the second one"
    against a list of primary keys survives the documents themselves changing,
    and keeps the session small.
    """

    def __init__(self, data: Optional[dict] = None):
        data = data or {}
        self.last_result_ids: list[int] = list(data.get('last_result_ids') or [])
        self.last_query: str = data.get('last_query') or ''
        self.last_filters: dict = dict(data.get('last_filters') or {})
        self.focus_id: Optional[int] = data.get('focus_id')
        self.turns: int = int(data.get('turns') or 0)

    def as_dict(self) -> dict:
        return {
            'last_result_ids': self.last_result_ids[:MAX_TRACKED_RESULTS],
            'last_query': self.last_query,
            'last_filters': self.last_filters,
            'focus_id': self.focus_id,
            'turns': self.turns,
        }

    @classmethod
    def load(cls, request) -> 'AgentContext':
        session = getattr(request, 'session', None)
        return cls(session.get(CONTEXT_KEY) if session else None)

    def save(self, request) -> None:
        session = getattr(request, 'session', None)
        if session is not None:
            session[CONTEXT_KEY] = self.as_dict()
            session.modified = True

    def clear_results(self) -> None:
        self.last_result_ids = []
        self.last_query = ''
        self.last_filters = {}


# --------------------------------------------------------------------------- #
# Retrieval, always permission-scoped
# --------------------------------------------------------------------------- #

def _scoped_filters(request, understanding: Understanding) -> dict:
    """Translate recognised entities into ``search_documents`` filters."""
    filters: dict[str, Any] = {}
    if understanding.year:
        filters['year'] = understanding.year
    if understanding.doc_type:
        filters['document_type'] = understanding.doc_type
    if understanding.program:
        filters['program'] = understanding.program
    if understanding.area_code:
        filters['qa_area'] = understanding.area_code

    # Identical scoping to the Repository: Faculty never see outside their areas.
    scope = faculty_area_scope(getattr(request, 'user', None))
    if scope is not None:
        filters['area_codes'] = list(scope) if scope else [NO_AREA_SENTINEL]
    return filters


def _run_search(request, understanding: Understanding, limit: int = MAX_TRACKED_RESULTS):
    """Retrieve using the system's own hybrid search rather than a second engine."""
    from search.search_service import search_documents

    filters = _scoped_filters(request, understanding)
    query = understanding.search_query()
    qs = search_documents(query, filters or None)
    qs = qs.select_related('program', 'acc_area', 'uploaded_by')
    return list(qs[:limit]), filters, query


# --------------------------------------------------------------------------- #
# Presentation helpers
# --------------------------------------------------------------------------- #

def _card(doc: Document) -> dict:
    """One document result card. Every field is read from the record."""
    program = doc.program.code if doc.program_id else ''
    # acc_area is authoritative and qa_area is legacy free text; they disagree on
    # real records (one document reads "Area IV - Research" in qa_area while its
    # acc_area is Area II). build_area_filter_q already prefers acc_area, so the
    # card has to as well or it labels a document with an area it is not in.
    area = (doc.acc_area.area_code if doc.acc_area_id else '') or doc.qa_area
    status = 'Archived' if doc.is_archived else 'Available'
    return {
        'id': doc.pk,
        'title': doc.title,
        'category': doc.document_type or program or 'Uncategorised',
        'program': program,
        'area': area,
        'year': doc.year,
        'file_type': (doc.file_type or '').upper(),
        'status': status,
        'uploaded': doc.uploaded_at.strftime('%b %d, %Y') if doc.uploaded_at else '',
        'view_url': reverse('documents:view', args=[doc.pk]),
        'detail_url': reverse('documents:detail', args=[doc.pk]),
    }


def _action(label: str, url: str, kind: str = 'link') -> dict:
    return {'label': label, 'url': url, 'kind': kind}


def _reply(answer: str, *, cards=None, actions=None, intent='', clarify=False,
           note='') -> dict:
    # `category` is part of the response contract the rules engine established and
    # that its tests assert on. The agent keeps the same shape and simply adds to
    # it, so any existing consumer of this endpoint is unaffected.
    return {
        'answer': answer,
        'category': 'archive_agent',
        'cards': cards or [],
        'actions': actions or [],
        'intent': intent,
        'clarify': clarify,
        'note': note,
        'source': 'agent',
    }


def _no_data(what: str, intent: str) -> dict:
    """The honest answer when the records cannot support one."""
    return _reply(
        f"I couldn't determine {what} from the available records.",
        intent=intent,
        note='Answered from the archive; nothing was inferred beyond it.',
    )


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _terms(keywords) -> list[str]:
    """
    Normalise a TF-IDF keyword list to plain terms.

    The pipeline stores ``[["quality assurance", 0.1433], ...]`` -- term/weight
    pairs, not strings -- so anything joining these has to unwrap them first.
    """
    out: list[str] = []
    for item in keywords or []:
        if isinstance(item, (list, tuple)):
            if item:
                out.append(str(item[0]))
        else:
            out.append(str(item))
    return out


# --------------------------------------------------------------------------- #
# Intent handlers
# --------------------------------------------------------------------------- #

def _handle_find(request, u: Understanding, ctx: AgentContext) -> dict:
    # A follow-up such as "which ones are from 2025?" narrows the previous set
    # instead of starting a new search.
    narrowing = u.refers_to_previous and ctx.last_result_ids
    if narrowing:
        qs = Document.objects.filter(pk__in=ctx.last_result_ids)
        if u.year:
            qs = qs.filter(year=u.year)
        if u.program:
            qs = qs.filter(program__code__iexact=u.program)
        if u.topics:
            topic_q = Q()
            for topic in u.topics:
                for term in nlu.TOPIC_TERMS.get(topic, []):
                    topic_q |= (Q(title__icontains=term) | Q(qa_area__icontains=term)
                                | Q(description__icontains=term))
            qs = qs.filter(topic_q)
        docs = list(qs.select_related('program', 'acc_area')[:MAX_TRACKED_RESULTS])
        basis = 'from the previous results'
    else:
        docs, filters, query = _run_search(request, u)
        ctx.last_filters = {k: v for k, v in filters.items() if k != 'area_codes'}
        ctx.last_query = query
        basis = ''

    ctx.last_result_ids = [d.pk for d in docs]
    ctx.focus_id = docs[0].pk if docs else None

    if not docs:
        described = _describe_criteria(u)
        # A Faculty search covers only their areas; saying "the archive" implied
        # nothing exists anywhere.
        where = 'in your area(s)' if faculty_area_scope(getattr(request, 'user', None)) is not None else 'in the archive'
        return _reply(
            f"No documents {where} are {described}." if described
            else f"I couldn't find any documents {where} matching that.",
            intent=nlu.FIND_DOCUMENTS,
            actions=[_action('Open Repository', reverse('documents:repository')),
                     _action('Search again', reverse('documents:repository'), 'search')],
            note='Searched the archive; no matching records exist.',
        )

    described = _describe_criteria(u)
    shown = docs[:PAGE_SIZE]
    headline = (f"I found {len(docs)} {_plural(len(docs), 'document', 'documents')}"
                f"{(' ' + described) if described else ''}"
                f"{(' ' + basis) if basis else ''}.")
    if len(docs) > len(shown):
        headline += f" Showing the first {len(shown)}."

    actions = [_action('Open Repository', _repository_url(u))]
    if len(docs) > len(shown):
        actions.append(_action('View all results', _repository_url(u)))
    return _reply(headline, cards=[_card(d) for d in shown],
                  actions=actions, intent=nlu.FIND_DOCUMENTS)


def _repository_url(u: Understanding) -> str:
    """Deep-link into the Repository carrying the same criteria."""
    from urllib.parse import urlencode
    params = {}
    if u.search_query():
        params['q'] = u.search_query()
    if u.year:
        params['year'] = u.year
    base = reverse('documents:repository')
    return f'{base}?{urlencode(params)}' if params else base


def _describe_criteria(u: Understanding) -> str:
    bits = []
    if u.topics:
        bits.append(' and '.join(u.topics))
    elif u.subject:
        bits.append(f'about "{u.subject}"')
    if u.program:
        bits.append(f'under {u.program}')
    if u.area_code:
        bits.append(f'in {u.area_code}')
    if u.doc_type:
        bits.append(f'of type {u.doc_type}')
    if u.year:
        bits.append(f'from {u.year}')
    if not bits:
        return ''
    if u.topics:
        first = bits[0]
        rest = bits[1:]
        return f"related to {first}" + (' ' + ' '.join(rest) if rest else '')
    return ' '.join(bits)


# Words that ask for something to be done to a document rather than name one:
# "summarize the fire safety certificate" names "fire safety certificate".
_REQUEST_WORDS = frozenset("""
    summarize summarise summarized summarised summary tldr tl dr gist brief overview
    explain why how is was are were did does do it its this that these those the a an
    of me please give can you could would tell about what say says said contain contains
    cover covers key important main points information details put placed filed assigned
    sorted in under into on classified classification categorized categorised category
    grouped group cluster clustered type program programme document documents file files
    record records one first second third fourth fifth last so there belong belongs to
    for as and or with way which
""".split())

_POINTS_AT_ONE = re.compile(r'\b(this|that)\s+(file|document|record|one)\b|\bit\b', re.I)


def _named_document(request, u: Understanding) -> tuple[str, Optional[Document]]:
    """
    The document a message names, as (name, match).

    A name is what is left once the request words are removed. Without this,
    "summarize the fire safety certificate" summarised whatever the previous
    answer had been about. ('', None) means no name was given, so the previous
    answer is what the user means; (name, None) means nothing matched the name.
    """
    if u.ordinal or _POINTS_AT_ONE.search(u.raw):
        return '', None
    text = nlu._AREA_RE.sub(' ', u.raw.lower())
    text = re.sub(r'\b(?:19|20)\d{2}\b', ' ', text)
    name = ' '.join(w for w in re.findall(r"[a-z0-9]+", text) if w not in _REQUEST_WORDS)
    if not name:
        return '', None
    from search.search_service import search_documents
    scope = faculty_area_scope(getattr(request, 'user', None))
    filters = {'area_codes': list(scope) if scope else [NO_AREA_SENTINEL]} if scope is not None else None
    return name, search_documents(name, filters).select_related('program', 'acc_area').first()


def _not_found_by_name(request, name: str, intent: str) -> dict:
    where = ' in your area(s)' if faculty_area_scope(getattr(request, 'user', None)) is not None else ''
    from urllib.parse import urlencode
    return _reply(
        f'I couldn\'t find a document matching "{name}"{where}. '
        'Check the spelling, or search the Repository and ask again about the one you open.',
        intent=intent, clarify=True,
        actions=[_action('Search the Repository',
                         f"{reverse('documents:repository')}?{urlencode({'q': name})}")],
    )


def _resolve_focus(u: Understanding, ctx: AgentContext) -> Optional[Document]:
    """Turn "the second one" / "it" into an actual row."""
    ids = ctx.last_result_ids
    if u.ordinal and ids:
        index = u.ordinal - 1 if u.ordinal > 0 else len(ids) - 1
        if 0 <= index < len(ids):
            return Document.objects.filter(pk=ids[index]).first()
        return None
    if ctx.focus_id:
        return Document.objects.filter(pk=ctx.focus_id).first()
    if ids:
        return Document.objects.filter(pk=ids[0]).first()
    return None


def _handle_summarize(request, u: Understanding, ctx: AgentContext) -> dict:
    name, doc = _named_document(request, u)
    if name and doc is None:
        return _not_found_by_name(request, name, nlu.SUMMARIZE)
    doc = doc or _resolve_focus(u, ctx)
    if doc is None:
        return _reply(
            "Which document would you like summarised? Search for it first, "
            "or open one from the Repository and ask again.",
            intent=nlu.SUMMARIZE, clarify=True,
            actions=[_action('Open Repository', reverse('documents:repository'))],
        )
    if not _visible_to(request, doc):
        return _reply("That document is outside the areas assigned to you.",
                      intent=nlu.SUMMARIZE)

    ctx.focus_id = doc.pk
    text = (doc.extracted_text or doc.ocr_text or '').strip()
    if not text:
        return _reply(
            f"“{doc.title}” has no extracted text yet, so I cannot summarise its "
            f"contents. Its recorded details are below.",
            cards=[_card(doc)], intent=nlu.SUMMARIZE,
            actions=[_action('View Document', reverse('documents:view', args=[doc.pk]))],
            note='No OCR/extracted text is stored for this record.',
        )

    summary = _extractive_summary(text, doc)
    keywords = _terms(doc.tfidf_keywords)[:6]
    answer = f"**{doc.title}**\n\n{summary}"
    if keywords:
        answer += "\n\nKey terms: " + ', '.join(keywords)
    return _reply(answer, cards=[_card(doc)], intent=nlu.SUMMARIZE,
                  actions=[_action('View Document', reverse('documents:view', args=[doc.pk])),
                           _action('View Related Documents', _related_url(doc))],
                  note='Summarised from the text stored for this document.')


def _extractive_summary(text: str, doc: Document, max_sentences: int = 3) -> str:
    """
    Pick the sentences that best represent the document.

    Extractive on purpose: the sentences come from the file itself, so nothing in
    a summary is language the agent invented. Sentences are ranked by how many of
    the document's own TF-IDF keywords they carry -- reusing the keyword set the
    analysis pipeline already computed rather than scoring from scratch.
    """
    clean = re.sub(r'\s+', ' ', text).strip()
    sentences, seen = [], set()
    for s in re.split(r'(?<=[.!?])\s+', clean):
        s = s.strip()
        key = s.lower()
        # Headers and footers repeat on every page; a summary should say it once.
        if len(s) > 40 and key not in seen:
            seen.add(key)
            sentences.append(s)
    if not sentences:
        return clean[:400] + ('…' if len(clean) > 400 else '')

    keywords = {k.lower() for k in _terms(doc.tfidf_keywords)}
    if not keywords:
        return ' '.join(sentences[:max_sentences])[:600]

    scored = []
    for position, sentence in enumerate(sentences[:60]):
        lowered = sentence.lower()
        hits = sum(1 for k in keywords if k and k in lowered)
        # a mild preference for earlier sentences, which usually carry the purpose
        scored.append((hits - position * 0.01, position, sentence))
    scored.sort(reverse=True)
    chosen = sorted(scored[:max_sentences], key=lambda item: item[1])
    return ' '.join(s for _, _, s in chosen)[:700]


def _related_url(doc: Document) -> str:
    if doc.cluster_label is not None:
        return f"{reverse('documents:clusters')}?cluster={doc.cluster_label}"
    return reverse('documents:repository')


def _handle_explain(request, u: Understanding, ctx: AgentContext) -> dict:
    name, doc = _named_document(request, u)
    if name and doc is None:
        return _not_found_by_name(request, name, nlu.EXPLAIN_CLASSIFICATION)
    doc = doc or _resolve_focus(u, ctx)
    if doc is None:
        return _reply(
            "Which document's classification would you like explained? "
            "Search for it first, then ask again.",
            intent=nlu.EXPLAIN_CLASSIFICATION, clarify=True,
            actions=[_action('Open Repository', reverse('documents:repository'))],
        )
    if not _visible_to(request, doc):
        return _reply("That document is outside the areas assigned to you.",
                      intent=nlu.EXPLAIN_CLASSIFICATION)

    ctx.focus_id = doc.pk
    lines = [f"**{doc.title}**", ""]
    grounded = False

    if doc.program_id:
        lines.append(f"- Programme: **{doc.program.code} — {doc.program.name}**, set on the record.")
        grounded = True
    if doc.document_type:
        lines.append(f"- Document type: **{doc.document_type}**.")
        grounded = True
    if doc.qa_area:
        lines.append(f"- QA area: **{doc.qa_area}**.")
        grounded = True
    if doc.acc_area_id:
        lines.append(f"- Accreditation area: **{doc.acc_area.area_code} — {doc.acc_area.area_name}**.")
        grounded = True

    if doc.cluster_label is not None:
        result = (ClusterResult.objects.live().filter(cluster_number=doc.cluster_label)
                  .order_by('-created_at').first())
        label = (result.cluster_label if result and result.cluster_label
                 else f'Cluster {doc.cluster_label}')
        # Peers the asker may see, not counting this document ("N other").
        peers = scope_documents_for_user(
            Document.objects.live().filter(cluster_label=doc.cluster_label, is_archived=False),
            getattr(request, 'user', None),
        ).exclude(pk=doc.pk).count()
        lines.append(
            f"- K-Means grouped it into **{label}** with "
            f"{peers} other {_plural(peers, 'document', 'documents')}, based on the "
            f"similarity of its extracted text."
        )
        if result and result.top_keywords:
            lines.append(f"  Cluster keywords: {', '.join(_terms(result.top_keywords)[:6])}.")
        grounded = True

    if doc.tfidf_keywords:
        lines.append(
            "- TF-IDF picked these as the document's most distinctive terms: "
            + ', '.join(_terms(doc.tfidf_keywords)[:8]) + '.'
        )
        grounded = True

    if not grounded:
        return _no_data(f"how “{doc.title}” was classified",
                        nlu.EXPLAIN_CLASSIFICATION)

    return _reply('\n'.join(lines), cards=[_card(doc)],
                  intent=nlu.EXPLAIN_CLASSIFICATION,
                  actions=[_action('View Document', reverse('documents:view', args=[doc.pk])),
                           _action('View Related Documents', _related_url(doc))],
                  note='Read from the stored classification, cluster and TF-IDF results.')


def _handle_missing(request, u: Understanding, ctx: AgentContext) -> dict:
    """
    Say plainly that the system no longer tracks what is required.

    This answer was built on two sources and both have since been removed as out
    of scope: the accreditation hierarchy's required-evidence records, and then
    the QA checklist's requirement records. Nothing left in the archive states
    what *ought* to exist, so the honest reply is that the question cannot be
    answered from the data -- not a zero, which would read as "nothing is
    missing".
    """
    answer = (
        "This system does not record what evidence is required, so it cannot say what is "
        "outstanding. It archives what has been uploaded and files it by accreditation area "
        "and QA program. To see who has submitted what, open Area Submissions; to find a "
        "document, use the Repository.")
    area = _area_record(u.area_code)
    if area is None:
        return _reply(answer, intent=nlu.MISSING_EVIDENCE,
                      note='Answered from the archive; nothing was inferred beyond it.')
    lines, cards, actions = _area_overview(request, area)
    return _reply(answer + '\n\nWhat is already archived for it:\n\n' + '\n'.join(lines),
                  cards=cards, actions=actions, intent=nlu.MISSING_EVIDENCE,
                  note='Answered from the archive; nothing was inferred beyond it.')


def _area_record(code: Optional[str]):
    from qa_structure.models import AccreditationArea
    if not code:
        return None
    return AccreditationArea.objects.filter(area_code__iexact=code).first()


def _area_documents(request, code: str):
    from documents.area_utils import build_area_filter_q
    return scope_documents_for_user(
        Document.objects.live().filter(is_archived=False), getattr(request, 'user', None),
    ).filter(build_area_filter_q([code]))


def _area_overview(request, area) -> tuple[list[str], list[dict], list[dict]]:
    """One area's name, description and what the asker can see archived in it."""
    from urllib.parse import urlencode
    lines = [f'**{area.area_code} — {area.area_name}**']
    if area.description:
        lines.append(area.description.strip())
    scope = faculty_area_scope(getattr(request, 'user', None))
    if scope is not None and area.area_code not in scope:
        lines.append("This area is not assigned to you, so its documents are not visible to you.")
        return lines, [], []
    docs = _area_documents(request, area.area_code).order_by('-uploaded_at')
    total = docs.count()
    if total:
        lines.append(f"{total} {_plural(total, 'document is', 'documents are')} archived in it; "
                     "the most recent are below.")
    else:
        lines.append('Nothing is archived in it yet.')
    url = f"{reverse('documents:repository')}?{urlencode({'area': area.area_code})}"
    return lines, [_card(d) for d in docs[:3]], [_action(f'Open {area.area_code} in the Repository', url)]


_ASKS_WHAT_TO_UPLOAD = re.compile(r'\b(upload|submit|provide|put)\b', re.I)


def _handle_area(request, u: Understanding, ctx: AgentContext) -> dict:
    from qa_structure.models import AccreditationArea
    from qa_structure.utils_ordering import area_roman_sort_key

    if u.area_code:
        area = _area_record(u.area_code)
        if area is None:
            return _reply(f"There is no {u.area_code} among this system's accreditation areas. "
                          "Ask \"What are the accreditation areas?\" to see them.",
                          intent=nlu.AREA_INFO)
        lines, cards, actions = _area_overview(request, area)
        if _ASKS_WHAT_TO_UPLOAD.search(u.raw):
            lines.insert(0, "This system does not keep a list of the evidence each area requires, "
                            "so I can't say exactly what to upload — follow the accreditation "
                            "instrument your office uses. Here is the area and what it already has:\n")
            actions = actions + [_action('Upload Document', reverse('documents:bulk_upload'))]
        return _reply('\n'.join(lines), cards=cards, actions=actions, intent=nlu.AREA_INFO,
                      note='Read from the accreditation areas and the archive.')

    areas = sorted(AccreditationArea.objects.all(), key=lambda a: area_roman_sort_key(a.area_code))
    if not areas:
        return _no_data('the accreditation areas', nlu.AREA_INFO)
    scope = faculty_area_scope(getattr(request, 'user', None))
    lines = ['The accreditation areas in this system:', '']
    for area in areas:
        if scope is not None and area.area_code not in scope:
            lines.append(f'- **{area.area_code}** — {area.area_name}')
            continue
        n = _area_documents(request, area.area_code).count()
        lines.append(f"- **{area.area_code}** — {area.area_name} ({n} {_plural(n, 'document', 'documents')})")
    if scope is not None:
        lines.append('\nDocument counts are shown for your assigned area(s) only.')
    lines.append('\nAsk about one, e.g. "What is Area II about?"')
    return _reply('\n'.join(lines), intent=nlu.AREA_INFO,
                  actions=[_action('Open Repository', reverse('documents:repository'))],
                  note='Read from the accreditation areas and the archive.')


_PERIOD_LABELS = {
    'today': 'today', 'yesterday': 'yesterday',
    'this week': 'in the last 7 days', 'last week': 'in the 7 days before that',
    'this month': 'this month', 'last month': 'last month',
}


def _period_bounds(period: str):
    """Start and end of a period. "This week" is the last 7 days, as on the Dashboard."""
    from datetime import datetime, time, timedelta
    from django.utils import timezone

    now = timezone.localtime()
    midnight = timezone.make_aware(datetime.combine(now.date(), time.min))
    first_of_month = midnight.replace(day=1)
    if period == 'today':
        return midnight, None
    if period == 'yesterday':
        return midnight - timedelta(days=1), midnight
    if period == 'this week':
        return now - timedelta(days=7), None
    if period == 'last week':
        return now - timedelta(days=14), now - timedelta(days=7)
    if period == 'this month':
        return first_of_month, None
    previous = (first_of_month - timedelta(days=1)).replace(day=1)
    return previous, first_of_month


def _handle_period(request, u: Understanding, ctx: AgentContext) -> dict:
    start, end = _period_bounds(u.period)
    qs = scope_documents_for_user(Document.objects.live().filter(is_archived=False),
                                  getattr(request, 'user', None)).filter(uploaded_at__gte=start)
    if end is not None:
        qs = qs.filter(uploaded_at__lt=end)
    if u.area_code:
        from documents.area_utils import build_area_filter_q
        qs = qs.filter(build_area_filter_q([u.area_code]))
    qs = qs.select_related('program', 'acc_area').order_by('-uploaded_at')
    total = qs.count()
    docs = list(qs[:MAX_TRACKED_RESULTS])
    ctx.last_result_ids = [d.pk for d in docs]
    ctx.focus_id = docs[0].pk if docs else None

    label = _PERIOD_LABELS[u.period]
    where = f' in {u.area_code}' if u.area_code else ''
    if faculty_area_scope(getattr(request, 'user', None)) is not None:
        where += ' in your area(s)' if not u.area_code else ''
    if not total:
        return _reply(f'No documents were uploaded{where} {label}.', intent=nlu.UPLOADED_IN_PERIOD,
                      actions=[_action('Open Repository', reverse('documents:repository'))])
    headline = (f"{total} {_plural(total, 'document was', 'documents were')} uploaded{where} {label}.")
    if total > PAGE_SIZE:
        headline += f' Showing the {PAGE_SIZE} most recent.'
    return _reply(headline, cards=[_card(d) for d in docs[:PAGE_SIZE]], intent=nlu.UPLOADED_IN_PERIOD,
                  actions=[_action('Open Repository', reverse('documents:repository'))],
                  note='Counted from the upload dates in the archive.')


def _handle_count(request, u: Understanding, ctx: AgentContext) -> dict:
    docs, filters, query = _run_search(request, u)
    described = _describe_criteria(u)
    total = len(docs)
    if total == MAX_TRACKED_RESULTS:
        from search.search_service import search_documents
        total = search_documents(query, filters or None).count()
    ctx.last_result_ids = [d.pk for d in docs]
    return _reply(
        f"There {'is' if total == 1 else 'are'} **{total}** "
        f"{_plural(total, 'document', 'documents')}"
        f"{(' ' + described) if described else ' in the archive'}.",
        cards=[_card(d) for d in docs[:3]],
        intent=nlu.COUNT_DOCUMENTS,
        actions=[_action('Open Repository', _repository_url(u))],
        note='Counted from the archive.',
    )


def _handle_categories(request, u: Understanding, ctx: AgentContext) -> dict:
    from qa_mapping.models import QAProgram
    programs = list(QAProgram.objects.filter(is_active=True).values_list('code', 'name'))
    types = (scope_documents_for_user(Document.objects.live().filter(is_archived=False),
                                      getattr(request, 'user', None))
             .exclude(document_type='')
             .values('document_type').annotate(n=Count('id')).order_by('-n')[:10])
    lines = []
    if programs:
        lines.append('**QA programmes**')
        lines += [f'- {code} — {name}' for code, name in programs]
    if types:
        lines.append('\n**Document types in the archive**')
        lines += [f"- {t['document_type']} ({t['n']})" for t in types]
    if not lines:
        return _no_data('the available categories', nlu.LIST_CATEGORIES)
    return _reply('\n'.join(lines), intent=nlu.LIST_CATEGORIES,
                  actions=[_action('Open Repository', reverse('documents:repository'))],
                  note='Listed from the programme and document records.')


_NOT_DOCUMENTS = re.compile(
    r'\b(users?|accounts?|people|persons?|members?|duplicates?|clusters?|programs?|programmes?|areas)\b', re.I)
_DOCUMENT_WORDS = re.compile(r'\b(documents?|files?|records?|evidence|uploads?|reports?)\b', re.I)


def _is_filtered_document_count(u: Understanding) -> bool:
    """ "How many documents are in Area II?" -- a count of documents, narrowed."""
    if _NOT_DOCUMENTS.search(u.raw):
        return False
    if u.area_code or u.year or u.program or u.doc_type:
        return True
    return bool((u.topics or u.subject) and _DOCUMENT_WORDS.search(u.raw))


def _visible_to(request, doc: Document) -> bool:
    """Faculty must not reach a document outside their assigned areas."""
    scope = faculty_area_scope(getattr(request, 'user', None))
    if scope is None:
        return True
    allowed = set(scope or [])
    # Same precedence as build_area_filter_q: acc_area decides, qa_area is the
    # fallback only when no accreditation area is set.
    if doc.acc_area_id:
        return doc.acc_area.area_code in allowed
    return bool(doc.qa_area) and doc.qa_area in allowed


# --------------------------------------------------------------------------- #
# Ambiguity
# --------------------------------------------------------------------------- #

# Empty on purpose.
#
# This held {'evaluation': ['Faculty Evaluation', 'Curriculum Evaluation',
# 'Student Evaluation']}, and the assistant offered those three as buttons. None
# of them exists: they are not document types -- the archive uses Document,
# Report, Certificate, Research, Manual, Form and Minutes -- and no document
# title contains any of the three. Every button led to an empty result set.
#
# Add an entry here only for a term the archive really does use in more than one
# sense, with options taken from stored values.
_AMBIGUOUS_TOPICS: dict[str, list[str]] = {}


def _needs_clarification(u: Understanding) -> Optional[dict]:
    """
    Ask rather than guess.

    "Show me the evaluation documents" could mean several things, and answering
    the wrong one wastes more of the user's time than a single question does.
    """
    if u.intent != nlu.FIND_DOCUMENTS:
        return None
    if u.year or u.program or u.doc_type or u.area_code:
        return None  # a qualifier is present; that is specific enough
    for topic, options in _AMBIGUOUS_TOPICS.items():
        if u.topics == [topic]:
            return _reply(
                "Sure. Which evaluation records do you mean: "
                + ', '.join(options[:-1]) + f', or {options[-1]}?',
                intent=u.intent, clarify=True,
                actions=[_action(opt, '#', 'suggest') for opt in options],
            )
    return None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def answer(message: str, request) -> Optional[dict]:
    """
    Produce an agent reply, or None when this is not an archive question.

    Returning None lets the caller fall back to the existing navigation and
    help engine, so none of that behaviour is lost.
    """
    from .scope import is_off_topic

    lowered = (message or '').strip().lower()
    if not lowered or is_off_topic(lowered):
        # "tell me a joke about cats" and "how many countries are in the world"
        # must reach the existing out-of-scope refusal, not this agent.
        return None

    u = nlu.understand(message)
    if u.intent in (nlu.UNKNOWN, nlu.NAVIGATION):
        return None

    # A weak signal is not an intent. Without a floor, a stray "about" scores 2
    # and turns an unrelated sentence into a document search.
    #
    # A back-reference is the exception. "Which ones are from 2025?" carries no
    # verb of its own and scores low, but pointing at the previous answer is a
    # strong signal in itself -- provided there is a previous answer to point at.
    ctx_peek = AgentContext.load(request)
    following_up = u.refers_to_previous and bool(ctx_peek.last_result_ids)
    if u.confidence < MIN_CONFIDENCE and not following_up:
        return None

    # A search has to be about something. Requiring a recognised subject stops
    # "what does the dashboard show" -- which scores on the verb alone -- from
    # being treated as a request for documents.
    # An explicit subject counts even when it is not one of the office's known
    # topics: "documents about zebra crossings" used to fall through to the
    # navigation help, which answered it with the upload instructions.
    if u.intent == nlu.FIND_DOCUMENTS and not (
        u.topics or u.program or u.year or u.doc_type or u.area_code
        or u.refers_to_previous or u.subject
    ):
        return None

    ctx = AgentContext.load(request)
    ctx.turns += 1

    clarification = _needs_clarification(u)
    if clarification is not None:
        ctx.save(request)
        return clarification

    # A plain count ("how many documents do we have?") stays with the rules
    # engine's live-data handler, which answers it and is covered by its own
    # tests. A count narrowed to an area, year, type, programme or subject is
    # answered here, because the live-data totals cannot filter.
    handlers = {
        nlu.FIND_DOCUMENTS: _handle_find,
        nlu.SUMMARIZE: _handle_summarize,
        nlu.EXPLAIN_CLASSIFICATION: _handle_explain,
        nlu.MISSING_EVIDENCE: _handle_missing,
        nlu.LIST_CATEGORIES: _handle_categories,
        nlu.AREA_INFO: _handle_area,
        nlu.UPLOADED_IN_PERIOD: _handle_period,
    }
    if u.intent == nlu.COUNT_DOCUMENTS:
        if u.period:
            handlers[nlu.COUNT_DOCUMENTS] = _handle_period
        elif _is_filtered_document_count(u):
            handlers[nlu.COUNT_DOCUMENTS] = _handle_count
    handler = handlers.get(u.intent)
    if handler is None:
        return None

    result = handler(request, u, ctx)
    ctx.save(request)

    if u.corrections:
        pairs = ', '.join(f'"{a}" → "{b}"' for a, b in u.corrections[:3])
        result['note'] = (result.get('note', '') + f' Read {pairs}.').strip()
    return result

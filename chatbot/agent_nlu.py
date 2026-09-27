"""
Natural-language understanding for the QA Archive Agent.

Intent and entity recognition without an external API. The system already carries
the vocabulary this needs -- programme codes, accreditation areas, document types
and the TF-IDF keyword sets on each document -- so meaning is derived from those
rather than from a hosted model.

The matcher is deliberately not a bag of exact keywords. Each intent owns a set of
*signals*: verbs, objects and phrasings that point at it. A message scores against
every intent and the strongest wins, so "find accreditation documents", "show me
files related to accreditation", "what accreditation records do we have" and
"I need the documents for accreditation" all land on FIND_DOCUMENTS even though
they share only the word "accreditation".

Misspellings are handled by a bounded edit-distance pass over the QA vocabulary,
so "acreditation", "accrediation" and "facutly" still resolve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# QA vocabulary. These are the terms the office actually uses; they drive both
# entity extraction and the spelling correction below.
# --------------------------------------------------------------------------- #

PROGRAM_ALIASES = {
    'pqa': 'PQA',
    'philippine quality award': 'PQA',
    'iso': 'ISO',
    'iso audit': 'ISO',
    'iso internal': 'ISO-INT',
    'internal audit': 'ISO-INT',
    'iso external': 'ISO-EXT',
    'external audit': 'ISO-EXT',
    'baics': 'BAICS',
    'ia': 'IA',
    'institutional accreditation': 'IA',
    'accreditation': 'ACCRED',
    'accred': 'ACCRED',
    'aaccup': 'ACCRED',
}

# Subject areas the office talks about, mapped to the words that appear in
# document titles, qa_area values and extracted text.
TOPIC_TERMS = {
    'accreditation': ['accreditation', 'accredit', 'aaccup', 'survey', 'accreditor'],
    'faculty': ['faculty', 'teacher', 'instructor', 'teaching', 'academic staff'],
    'evaluation': ['evaluation', 'evaluate', 'assessment', 'appraisal', 'rating'],
    'curriculum': ['curriculum', 'syllabus', 'course', 'program of study', 'instruction'],
    'research': ['research', 'publication', 'journal', 'study'],
    'extension': ['extension', 'community', 'outreach'],
    'library': ['library', 'collection', 'holdings'],
    'laboratory': ['laboratory', 'lab', 'equipment'],
    'administration': ['administration', 'governance', 'organizational'],
    'compliance': ['compliance', 'comply', 'conformance', 'conformity'],
    'audit': ['audit', 'auditor', 'finding', 'nonconformity'],
    'policy': ['policy', 'policies', 'manual', 'guideline'],
    'student': ['student', 'learner', 'enrollee', 'support to students'],
    'facilities': ['facilities', 'physical plant', 'building', 'campus'],
}

DOC_TYPE_TERMS = {
    'report': ['report'],
    'policy': ['policy', 'policies'],
    'manual': ['manual', 'handbook'],
    'form': ['form', 'template'],
    'certificate': ['certificate', 'certification'],
    'minutes': ['minutes', 'minute'],
    'memo': ['memo', 'memorandum'],
    'plan': ['plan'],
}

# Everything above, flattened, for the spelling pass.
_VOCAB: set[str] = set()
for _terms in list(TOPIC_TERMS.values()) + list(DOC_TYPE_TERMS.values()):
    for _t in _terms:
        _VOCAB.update(_t.split())
_VOCAB.update(PROGRAM_ALIASES.keys())
_VOCAB.update({
    'document', 'documents', 'evidence', 'record', 'records', 'file', 'files',
    'missing', 'summarize', 'summary', 'classify', 'classification', 'category',
    'archive', 'archived', 'upload', 'uploaded', 'requirement', 'requirements',
    'area', 'parameter', 'indicator', 'cluster', 'duplicate', 'metadata',
})


# --------------------------------------------------------------------------- #
# Intents
# --------------------------------------------------------------------------- #

FIND_DOCUMENTS = 'find_documents'
MISSING_EVIDENCE = 'missing_evidence'
SUMMARIZE = 'summarize'
EXPLAIN_CLASSIFICATION = 'explain_classification'
COUNT_DOCUMENTS = 'count_documents'
LIST_CATEGORIES = 'list_categories'
AREA_INFO = 'area_info'
UPLOADED_IN_PERIOD = 'uploaded_in_period'
NAVIGATION = 'navigation'
UNKNOWN = 'unknown'

# Each entry: (weight, compiled pattern). Weights let a specific phrasing beat a
# generic one -- "what documents are missing" must not be read as a plain search
# just because it contains the word "documents".
_INTENT_SIGNALS: dict[str, list[tuple[int, str]]] = {
    MISSING_EVIDENCE: [
        (5, r'\b(missing|lacking|absent|incomplete|outstanding|still need|do we need|left to)\b'),
        (5, r"\b(haven'?t|have not|not yet)\b.*\b(upload|submit|provide|complete)"),
        (4, r'\bwhat.*\b(need|require)\w*\b.*\b(for|to)\b'),
        (3, r'\b(gap|gaps|shortfall|gap analysis)\b'),
        (2, r'\b(evidence|requirement|requirements)\b'),
    ],
    SUMMARIZE: [
        (5, r'\b(summar\w+|tl;?dr|gist|overview of this|brief)\b'),
        (4, r'\bwhat (is|are) (this|that|it) (file|document|record)?\s*(about)?\b'),
        (4, r'\b(important|key) (information|points|details)\b'),
        (3, r'\bwhat does (this|that|it) (say|contain|cover)\b'),
    ],
    EXPLAIN_CLASSIFICATION: [
        (5, r'\bwhy (is|was|are)\b.*\b(classif|categor|group|cluster|tag)\w*'),
        # "why was the certificate put in Area VIII?", "why is it under ISO?"
        (6, r'\bwhy (is|was|are|did)\b.*\b(put|placed|filed|assigned|sorted|in|under)\b'
            r'.*\b(area|program|programme|cluster|category|type)\b'),
        (5, r'\bwhat (category|classification|cluster|group|type)\b.*\b(belong|is|does)\b'),
        (4, r'\bhow (was|is) (this|that|it) (classif|categor|group)\w*'),
        (3, r'\b(classification|classified|categorized|clustered)\b'),
    ],
    COUNT_DOCUMENTS: [
        # "how many" is unambiguous and has to outrank a plain search, which also
        # scores on "documents" and "do we have" in the same sentence.
        (8, r'\bhow many\b'),
        (4, r'\b(total|count|number) of\b.*\b(document|file|record|evidence)'),
    ],
    AREA_INFO: [
        # "what are the accreditation areas?", "list the areas"
        (7, r'\b(what|which) are the (\w+ )?areas\b'),
        (7, r'\blist (all |the )?(\w+ )?areas\b'),
        # "what is Area IX about?", "what does area 4 cover?"
        (7, r'\bwhat (is|does)\s+area\s+([ivx]+|\d+)\b'),
        (5, r'\barea\s+([ivx]+|\d+)\b.*\b(about|cover|covers|mean|means|stand for)\b'),
        # "what should I upload for Area IV?"
        (7, r'\bwhat (should|do|must|can|shall) (i|we)\b.*\b(upload|submit|put|provide)\b.*\barea\b'),
    ],
    UPLOADED_IN_PERIOD: [
        # A time window. Bare "recent"/"latest" stays with the live-data tier.
        (8, r'\b(upload|uploads|uploaded|added|submitted|new)\b.*'
            r'\b(today|yesterday|this week|last week|this month|last month)\b'),
        (8, r'\b(today|yesterday|this week|last week|this month|last month)\b.*'
            r'\b(upload|uploads|uploaded|added|submitted)\b'),
    ],
    LIST_CATEGORIES: [
        (5, r'\b(what|which|list).*(categor|program|area|cluster)\w*\b.*\b(are there|do we have|exist|available)\b'),
        (4, r'\blist (all )?(categor|program|area|cluster)\w*'),
    ],
    FIND_DOCUMENTS: [
        (4, r'\b(find|show|list|get|give|retrieve|pull|display|search|look for|locate)\b'),
        (4, r'\b(do we have|do you have|are there|is there|what .* do we have)\b'),
        (3, r'\bi need\b|\bi want\b|\blooking for\b'),
        (3, r'\b(document|documents|file|files|record|records|evidence)\b'),
        (2, r'\b(related to|about|regarding|concerning|for)\b'),
        # "which documents mention X" asks for documents as plainly as "find".
        (2, r'\b(mention|mentions|mentioning|contain|contains|containing)\b'),
    ],
    NAVIGATION: [
        (5, r'\bwhere (is|are|do i|can i)\b'),
        (5, r'\bhow (do|can) i\b(?!.*\b(many|much)\b)'),
        (4, r'\b(navigate|sidebar|menu|button|page)\b'),
    ],
}

_COMPILED = {
    intent: [(w, re.compile(p, re.I)) for w, p in sigs]
    for intent, sigs in _INTENT_SIGNALS.items()
}


# --------------------------------------------------------------------------- #
# Spelling tolerance
# --------------------------------------------------------------------------- #

def _edit_distance_within(a: str, b: str, limit: int) -> bool:
    """Bounded Levenshtein: True when a and b differ by at most `limit` edits."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def correct_terms(message: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Repair misspelled QA terms so "acreditation" and "facutly" still match.

    Only words of five characters or more are considered, and only a one- or
    two-character edit is accepted, so ordinary English is left alone.
    """
    corrections: list[tuple[str, str]] = []

    def fix(match: re.Match) -> str:
        word = match.group(0)
        lower = word.lower()
        if len(lower) < 5 or lower in _VOCAB:
            return word
        limit = 1 if len(lower) < 8 else 2
        for term in _VOCAB:
            if len(term) >= 5 and _edit_distance_within(lower, term, limit):
                corrections.append((word, term))
                return term
        return word

    return re.sub(r'[A-Za-z]+', fix, message), corrections


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

@dataclass
class Understanding:
    """What the agent believes the user asked for."""
    intent: str = UNKNOWN
    confidence: int = 0
    year: Optional[int] = None
    program: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    doc_type: Optional[str] = None
    area_code: Optional[str] = None
    ordinal: Optional[int] = None
    refers_to_previous: bool = False
    corrections: list[tuple[str, str]] = field(default_factory=list)
    free_text: str = ''
    # What the user said the documents are about ("... about zebra crossings",
    # "... that mention rainwater harvesting"), whether or not it is one of the
    # office's known topics.
    subject: str = ''
    # 'today', 'yesterday', 'this week', 'last week', 'this month' or 'last month'.
    period: Optional[str] = None
    raw: str = ''

    def search_query(self) -> str:
        """The text handed to the retrieval engine."""
        parts = list(self.topics)
        if self.doc_type:
            parts.append(self.doc_type)
        return ' '.join(parts) if parts else (self.subject or self.free_text)


_ORDINALS = {
    'first': 1, '1st': 1, 'second': 2, '2nd': 2, 'third': 3, '3rd': 3,
    'fourth': 4, '4th': 4, 'fifth': 5, '5th': 5, 'last': -1,
}

# "which ones", "those", "them" -- a follow-up that leans on the previous answer.
_ANAPHORA = re.compile(
    r'\b(which ones?|those|them|these|they|it|that one|the (first|second|third|fourth|fifth|last) one)\b',
    re.I,
)

_AREA_RE = re.compile(r'\barea\s+([ivx]+|\d+)\b', re.I)
_ROMAN = {'i': 'I', 'ii': 'II', 'iii': 'III', 'iv': 'IV', 'v': 'V',
          'vi': 'VI', 'vii': 'VII', 'viii': 'VIII', 'ix': 'IX', 'x': 'X'}
_ARABIC_TO_ROMAN = {'1': 'I', '2': 'II', '3': 'III', '4': 'IV', '5': 'V',
                    '6': 'VI', '7': 'VII', '8': 'VIII', '9': 'IX', '10': 'X'}


def _extract_year(text: str) -> Optional[int]:
    this_year = datetime.now().year
    for token in re.findall(r'\b(19|20)\d{2}\b', text):
        pass
    match = re.findall(r'\b((?:19|20)\d{2})\b', text)
    for candidate in match:
        value = int(candidate)
        if 1990 <= value <= this_year + 2:
            return value
    if re.search(r'\bthis year\b', text, re.I):
        return this_year
    if re.search(r'\blast year\b', text, re.I):
        return this_year - 1
    return None


def _extract_program(text: str) -> Optional[str]:
    lowered = text.lower()
    # longest alias first so "iso internal" beats "iso"
    for alias in sorted(PROGRAM_ALIASES, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', lowered):
            return PROGRAM_ALIASES[alias]
    return None


def _extract_topics(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for topic, terms in TOPIC_TERMS.items():
        if any(re.search(rf'\b{re.escape(t)}', lowered) for t in terms):
            found.append(topic)
    return found


def _extract_doc_type(text: str) -> Optional[str]:
    lowered = text.lower()
    for label, terms in DOC_TYPE_TERMS.items():
        if any(re.search(rf'\b{re.escape(t)}\b', lowered) for t in terms):
            return label
    return None


def _extract_area(text: str) -> Optional[str]:
    match = _AREA_RE.search(text)
    if not match:
        return None
    token = match.group(1).lower()
    if token in _ROMAN:
        return f'Area {_ROMAN[token]}'
    if token in _ARABIC_TO_ROMAN:
        return f'Area {_ARABIC_TO_ROMAN[token]}'
    return None


_PERIOD_RE = re.compile(r'\b(today|yesterday|this week|last week|this month|last month)\b', re.I)


def _extract_period(text: str) -> Optional[str]:
    match = _PERIOD_RE.search(text)
    return match.group(1).lower() if match else None


def _extract_ordinal(text: str) -> Optional[int]:
    lowered = text.lower()
    for word, value in _ORDINALS.items():
        if re.search(rf'\b{re.escape(word)}\b', lowered):
            return value
    match = re.search(r'\b(?:number|no\.?|#)\s*(\d{1,2})\b', lowered)
    if match:
        return int(match.group(1))
    return None


def _strip_stopwords(text: str) -> str:
    """Leave the words that carry the subject, for the retrieval query."""
    noise = {
        'find', 'show', 'me', 'the', 'a', 'an', 'all', 'get', 'give', 'list',
        'please', 'can', 'you', 'i', 'need', 'want', 'looking', 'for', 'do',
        'we', 'have', 'what', 'which', 'are', 'is', 'there', 'any', 'documents',
        'document', 'files', 'file', 'records', 'record', 'related', 'to',
        'about', 'from', 'in', 'of', 'and', 'or', 'with', 'us', 'our', 'my',
        'display', 'retrieve', 'pull', 'search', 'look', 'up',
        # Counting words. Without these, "how many documents do we have" reduced
        # to the query "many" and searched the archive for that literal word,
        # which naturally matched nothing.
        'how', 'many', 'much', 'total', 'count', 'number', 'archive', 'system',
        # Phrasing around a subject: "what does the document about X say",
        # "documents that mention Y at the east gate". Every word left here must
        # appear in a matching document, so these would have excluded them all.
        'does', 'say', 'says', 'that', 'mention', 'mentions', 'mentioning', 'contain', 'contains',
        'containing', 'regarding', 'concerning', 'at', 'on', 'by',
    }
    words = [w for w in re.findall(r'[A-Za-z0-9-]+', text.lower()) if w not in noise]
    return ' '.join(words)


_SUBJECT_RE = re.compile(
    r'\b(?:about|regarding|concerning|related to|mention(?:s|ing)?|contain(?:s|ing)?)\s+(.+)', re.I)


def _extract_subject(text: str) -> str:
    """The words after "about" / "mentioning" ..., less a year or area (those are filters)."""
    match = _SUBJECT_RE.search(text)
    if not match:
        return ''
    tail = _AREA_RE.sub(' ', match.group(1))
    tail = re.sub(r'\b(?:19|20)\d{2}\b', ' ', tail)
    return _strip_stopwords(tail)


def understand(message: str) -> Understanding:
    """Classify one user message into an intent plus the entities it carries."""
    raw = (message or '').strip()
    if not raw:
        return Understanding(raw='')

    repaired, corrections = correct_terms(raw)

    scores: dict[str, int] = {}
    for intent, signals in _COMPILED.items():
        total = sum(weight for weight, pattern in signals if pattern.search(repaired))
        if total:
            scores[intent] = total

    # "this document" / "that file" / "it" points at a document the user already
    # has in view. That is the opposite of a search, so searching is demoted when
    # a singular deictic is present and no plural/collection word is.
    points_at_one = bool(re.search(
        r'\b(this|that)\s+(file|document|record|one)\b'
        r'|\bfrom this\b|\bis it about\b|\bof this\b',
        repaired, re.I))
    if points_at_one and FIND_DOCUMENTS in scores:
        scores[FIND_DOCUMENTS] = max(0, scores[FIND_DOCUMENTS] - 5)

    if scores:
        intent = max(scores, key=lambda k: scores[k])
        confidence = scores[intent]
    else:
        intent, confidence = UNKNOWN, 0

    result = Understanding(
        intent=intent,
        confidence=confidence,
        year=_extract_year(repaired),
        program=_extract_program(repaired),
        topics=_extract_topics(repaired),
        doc_type=_extract_doc_type(repaired),
        area_code=_extract_area(repaired),
        ordinal=_extract_ordinal(repaired),
        refers_to_previous=bool(_ANAPHORA.search(repaired)),
        corrections=corrections,
        # An area and a year are filters, not words a document must contain.
        free_text=_strip_stopwords(re.sub(r'\b(?:19|20)\d{2}\b', ' ', _AREA_RE.sub(' ', repaired))),
        subject=_extract_subject(repaired),
        period=_extract_period(repaired),
        raw=raw,
    )

    # A bare follow-up ("which ones are from 2025?") carries a year and a
    # back-reference but no verb of its own. Treat it as a refinement of the
    # previous search rather than as an unknown.
    if result.intent == UNKNOWN and result.refers_to_previous:
        result.intent = FIND_DOCUMENTS
        result.confidence = 2

    return result

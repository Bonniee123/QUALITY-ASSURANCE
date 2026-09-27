"""
Auto-metadata extraction from document content.
Reads the extracted text and attempts to identify title, year, document type, etc.
"""
import re
import os

_DESCRIPTION_MAX_LEN = 250
_SECTION_HEADINGS = (
    'abstract',
    'executive summary',
    'summary',
    'introduction',
    'overview',
    'background',
    'purpose',
    'objectives',
    'description',
    'rationale',
)
_JUNK_LINE_RE = re.compile(
    r'^(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*$|table\s+of\s+contents|contents|'
    r'chapter\s+\d+|appendix\s+[a-z0-9]+|references|bibliography)$',
    re.IGNORECASE,
)


# Document type is guessed from the first keyword found, in this order.
_TYPE_KEYWORDS = {
    'Policy': ['policy', 'policies', 'guideline', 'guidelines', 'regulation'],
    'Report': ['report', 'annual report', 'accomplishment', 'summary report'],
    'Manual': ['manual', 'handbook', 'guide', 'procedures manual'],
    'Plan': ['plan', 'strategic plan', 'development plan', 'action plan'],
    'Form': ['form', 'template', 'checklist form', 'evaluation form'],
    'Minutes': ['minutes', 'meeting minutes', 'proceedings'],
    'Memorandum': ['memorandum', 'memo', 'directive', 'advisory'],
    'Certificate': ['certificate', 'certification', 'accreditation'],
    'Syllabus': ['syllabus', 'course outline', 'course description'],
    'Research': ['research', 'study', 'thesis', 'dissertation', 'journal'],
    'Curriculum': ['curriculum', 'curricula', 'program of study'],
    'MOA/MOU': ['memorandum of agreement', 'moa', 'mou', 'memorandum of understanding'],
}
# Whole words, plus a plain plural. These keywords used to be searched as bare
# fragments, so "conform", "information" and "performance" each contain "form":
# an ISO certificate of registration was filed as a Form, and so was any report
# carrying performance data. The trailing "s" keeps what that looseness got
# right -- a text that says "reports" is still a Report.
_TYPE_PATTERNS = {
    doc_type: re.compile('|'.join(rf'\b{re.escape(kw)}s?\b' for kw in keywords))
    for doc_type, keywords in _TYPE_KEYWORDS.items()
}
# A file name's separators are word characters to a regex, which would stop
# "annual_report_2025.pdf" from matching the whole word "report".
_TYPE_SEPARATORS = re.compile(r'[_\-./\\]+')


def _type_haystack(text_lower):
    return _TYPE_SEPARATORS.sub(' ', text_lower)


def _normalize_whitespace(text):
    return re.sub(r'\s+', ' ', (text or '')).strip()


def _is_junk_line(line, title=''):
    s = _normalize_whitespace(line)
    if not s or len(s) < 12:
        return True
    if _JUNK_LINE_RE.match(s):
        return True
    if title and s.lower() == title.lower():
        return True
    # Mostly digits / punctuation
    letters = sum(ch.isalpha() for ch in s)
    if letters < len(s) * 0.35:
        return True
    # Short ALL-CAPS banner lines (e.g. "UNIVERSITY OF …")
    words = s.split()
    if len(words) <= 8 and s.isupper():
        return True
    return False


# Lines that open a letterheaded document and are never its title. Four unrelated
# documents -- a survey questionnaire, a data-gathering tool and two request
# letters -- were all archived as "Republic of the Philippines", because the
# extractor took the first line of text and that is what the first line says.
# In the repository they then looked like copies of one another while sitting in
# different clusters, which is correct for their content but reads as a fault.
_LETTERHEAD_RE = re.compile(
    r"^\s*(?:"
    r"republic\s+of\s+the\s+philippines"
    r"|republika\s+ng\s+pilipinas"
    r"|region\s+[ivxlc\d]+\b.*"
    r"|(?:province|city|municipality)\s+of\s+\w+"
    r")\s*$",
    re.IGNORECASE,
)

# An institution standing alone is a letterhead line too. The institution word has
# to END the line: "NORTH EASTERN MINDANAO STATE UNIVERSITY" is a masthead, while
# "University Library Annual Report 2026" is a real title that merely opens with
# the same word. An earlier version matched anywhere in the line and rejected the
# second one.
_INSTITUTION_RE = re.compile(
    r"^[\w\s\.,\-']*\b(?:university|college|institute|academy|campus)\s*$",
    re.IGNORECASE,
)

# The address under the institution. Recognised by shape rather than by place
# name: either it opens with a bullet or other symbol, or it carries at least two
# commas and ends in a four-digit post code. The comma requirement is what keeps
# "Annual Report 2026" -- which also ends in four digits -- out of this.
_ADDRESS_RE = re.compile(r"^[^\w\s].*\d{4}\s*$")


# The contact block that closes a masthead: a website, an email or a phone
# number, usually one per line under the address.
# The alternatives must consume the whole address, not just its opening: matching
# only "www." made a bare domain look like 4 characters of an otherwise ordinary
# line, and the share test below then let it through as a title.
_CONTACT_RE = re.compile(
    r"(?:https?://\S+|www\.\S+|[\w.\-]+@[\w.\-]+\.\w+|\(?\+?\d[\d\s\-()]{6,}\d)",
    re.IGNORECASE,
)


# Form-control footers on QA templates -- "FM-ACAD-005P/Rev.00/07.01.2019/ Page | 1".
# PDF extraction frequently emits these before the body, and sometimes runs one
# straight into the following line, so the code is matched as a prefix rather
# than as a whole line.
_FORM_CONTROL_RE = re.compile(r"^[A-Z]{2,}-[A-Z0-9\-]+/\s*Rev\.?\s*\d+", re.IGNORECASE)


def _looks_like_address(line):
    if _ADDRESS_RE.match(line):
        return True
    return line.count(',') >= 2 and re.search(r'\b\d{4}\s*$', line) is not None


def _looks_like_contact(line):
    """
    True when the line is mostly a web address, email or phone number.

    Measured as a share of the line so a real title that happens to mention a
    site ("Evaluation of www.example.com as a learning platform") is not caught:
    the contact string has to be most of what is there.
    """
    match = _CONTACT_RE.search(line)
    if not match:
        return False
    stripped = re.sub(r"^[^\w]+", '', line).strip()
    return len(match.group(0)) >= 0.6 * max(len(stripped), 1)


def _looks_like_letterhead(line):
    """True when a line is masthead boilerplate rather than a document title."""
    s = _normalize_whitespace(line)
    if not s:
        return True
    if _LETTERHEAD_RE.match(s):
        return True
    if _INSTITUTION_RE.match(s) and len(s.split()) <= 8:
        return True
    if _looks_like_address(s):
        return True
    if _looks_like_contact(s):
        return True
    if _FORM_CONTROL_RE.match(s):
        return True
    return False


def _title_from_text(text, max_lines=8):
    """
    The first line that reads like a title rather than a masthead.

    Letterheaded documents open with two or three lines of institution before the
    real subject line, so taking line one blindly gave every one of them the same
    title. Scanning past the boilerplate finds "SURVEY QUESTIONNAIRE" on line
    three instead. Returns '' when nothing looks like a title, which leaves the
    filename-derived default in place.
    """
    if not text:
        return ''
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    for line in lines[:max_lines]:
        candidate = line[:150]
        if len(candidate) <= 5 or len(candidate.split()) > 20:
            continue
        if _looks_like_letterhead(candidate):
            continue
        return candidate
    return ''


def _trim_to_sentence(text, max_len=_DESCRIPTION_MAX_LEN):
    text = _normalize_whitespace(text)
    if len(text) <= max_len:
        return text
    chunk = text[:max_len]
    last_period = chunk.rfind('.')
    if last_period >= int(max_len * 0.55):
        return chunk[: last_period + 1]
    last_space = chunk.rfind(' ')
    if last_space > 0:
        chunk = chunk[:last_space]
    return chunk.rstrip(' ,;:') + '…'


def _extract_section_paragraph(text):
    """Return prose after a known heading (Abstract, Introduction, etc.)."""
    if not text:
        return ''
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    heading_re = re.compile(
        r'^(' + '|'.join(re.escape(h) for h in _SECTION_HEADINGS) + r')\s*:?\s*$',
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines[:80]):
        if not heading_re.match(line):
            continue
        parts = []
        for follow in lines[idx + 1: idx + 12]:
            if _is_junk_line(follow):
                if parts:
                    break
                continue
            if heading_re.match(follow):
                break
            parts.append(follow)
            joined = _normalize_whitespace(' '.join(parts))
            if len(joined) >= 80:
                return _trim_to_sentence(joined)
        if parts:
            return _trim_to_sentence(' '.join(parts))
    return ''


def _first_meaningful_paragraph(text, title=''):
    """Pick the first readable paragraph, skipping title-like opening lines."""
    if not text:
        return ''
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    parts = []
    for line in lines[:60]:
        if _is_junk_line(line, title=title):
            if parts:
                break
            continue
        word_count = len(line.split())
        if word_count < 4 and not parts:
            continue
        parts.append(line)
        joined = _normalize_whitespace(' '.join(parts))
        if len(joined) >= 100 and (joined.endswith('.') or word_count >= 12):
            return _trim_to_sentence(joined)
        if len(joined) >= 180:
            return _trim_to_sentence(joined)
    if parts:
        return _trim_to_sentence(' '.join(parts))
    return ''


def _fallback_description(title='', document_type='', filename=''):
    label = (document_type or 'Document').strip()
    name = ''
    if filename:
        name = os.path.splitext(os.path.basename(filename))[0]
        name = re.sub(r'[_\-\.]+', ' ', name).strip()
    if title and name and title.lower() != name.lower():
        subject = title
    elif title:
        subject = title
    elif name:
        subject = name
    else:
        return ''
    return f'{label} — {subject}.'


def build_description(text, title='', document_type='', filename=''):
    """
    Build a short human-readable description from extracted document text.
    Prefers abstract/introduction sections, then the first real paragraph.
    """
    if not text or not _normalize_whitespace(text):
        return _fallback_description(title=title, document_type=document_type, filename=filename)

    candidate = _extract_section_paragraph(text)
    if len(candidate) < 40:
        candidate = _first_meaningful_paragraph(text, title=title)
    candidate = _normalize_whitespace(candidate)
    if len(candidate) >= 40:
        return candidate

    return _fallback_description(title=title, document_type=document_type, filename=filename)



def _years_in_name(filename):
    """Years 2000-2099 in a file name; "Report_2023" counts ("\b" does not split "_2023")."""
    return re.findall(r'(?<!\d)(20\d\d)(?!\d)', filename or '')


def extract_metadata_from_text(text, filename=''):
    """
    Analyze extracted text and filename to auto-fill metadata fields.

    Returns dict with: title, year, document_type, qa_area, criterion, indicator
    """
    metadata = {
        'title': '',
        'year': '',
        'document_type': '',
        'qa_area': '',
        'criterion': '',
        'indicator': '',
        'description': '',
    }

    # --- TITLE: Use filename (cleaned) as default title ---
    if filename:
        name = os.path.splitext(filename)[0]
        name = re.sub(r'[_\-\.]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        metadata['title'] = name.title()

    if text:
        derived = _title_from_text(text)
        if derived:
            metadata['title'] = derived

    # --- YEAR: Only use RELIABLE year patterns, NOT random years from references ---
    if text:
        text_upper = text[:3000]

        # Years 2000-2099 (this recognised only 2000-2029, so a 2031 plan was
        # silently given the current year).
        reliable_year_patterns = [
            r'(?:school\s*year|s\.?y\.?|academic\s*year|a\.?y\.?)\s*:?\s*(20\d\d)',
            r'(?:school\s*year|s\.?y\.?|academic\s*year|a\.?y\.?)\s*:?\s*(20\d\d)\s*[-–]\s*(20\d\d)',
            r'(?:dated?|as\s+of|effective)\s*:?\s*(?:\w+\s+\d{1,2}\s*,?\s*)?(20\d\d)',
            r'(?:fiscal\s*year|f\.?y\.?|calendar\s*year|c\.?y\.?)\s*:?\s*(20\d\d)',
            r'(?:approved|issued|published|revised)\s*:?\s*(?:\w+\s+\d{1,2}\s*,?\s*)?(20\d\d)',
            r'\bfor\s+the\s+year\s+(20\d\d)',
        ]

        year_found = ''
        for pattern in reliable_year_patterns:
            match = re.search(pattern, text_upper, re.IGNORECASE)
            if match:
                year_found = match.group(match.lastindex)
                break

        if not year_found:
            year_in_name = _years_in_name(filename)
            if year_in_name:
                year_found = year_in_name[-1]

        if not year_found:
            from datetime import datetime
            year_found = str(datetime.now().year)

        metadata['year'] = year_found

    else:
        year_in_name = _years_in_name(filename)
        if year_in_name:
            metadata['year'] = year_in_name[-1]
        else:
            from datetime import datetime
            metadata['year'] = str(datetime.now().year)

    combined_text = f"{filename} {text[:2000] if text else ''}"

    # --- DOCUMENT TYPE: Guess from content keywords ---
    text_lower = combined_text.lower()
    haystack = _type_haystack(text_lower)
    for doc_type, pattern in _TYPE_PATTERNS.items():
        if pattern.search(haystack):
            metadata['document_type'] = doc_type
            break

    if not metadata['document_type']:
        metadata['document_type'] = 'Document'

    metadata['description'] = build_description(
        text,
        title=metadata.get('title') or '',
        document_type=metadata.get('document_type') or '',
        filename=filename,
    )

    # --- QA AREA: the configured accreditation area the text is about ---
    metadata['qa_area'] = detect_area_code(text_lower[:5000] if text else '', filename)

    return metadata


# The ten accreditation areas as configured (qa_structure.AccreditationArea).
# Used only when the database cannot be read, e.g. in database-free tests.
_DEFAULT_AREAS = [
    ('Area I', 'Vision, Mission, Goals and Objectives'), ('Area II', 'Faculty'),
    ('Area III', 'Curriculum and Instruction'), ('Area IV', 'Support to Students'), ('Area V', 'Research'),
    ('Area VI', 'Extension and Community Involvement'), ('Area VII', 'Library'),
    ('Area VIII', 'Physical Plant and Facilities'), ('Area IX', 'Laboratories'), ('Area X', 'Administration'),
]

# What a document about each subject tends to say, and the word that subject's
# area has in its configured name. The map used to be keyed to its own list of
# area names, which ran one place behind the configured areas from Area IV on
# ("Area IV - Research" where Area V is Research), and the first subject
# mentioned won: one "faculty" in a laboratory manual filed it under Faculty.
_AREA_TOPICS = [
    ('vision', [r'vision', r'mission', r'goals? and objectives']),
    ('faculty', [r'faculty', r'instructors?', r'professors?', r'teaching (?:staff|load)']),
    ('curriculum', [r'curricul\w*', r'syllab\w*', r'course (?:outline|description)s?', r'instructional']),
    ('student', [r'student (?:services|affairs|development|welfare)', r'guidance', r'scholarships?',
                 r'support to students', r'admissions?']),
    ('research', [r'research\w*', r'thes[ie]s', r'dissertations?', r'publications?', r'journals?']),
    ('extension', [r'extension', r'community (?:service|involvement|outreach)', r'outreach']),
    ('library', [r'librar(?:y|ies|ian|ians)', r'periodicals', r'circulation']),
    ('physical', [r'physical (?:plant|facilit\w*)', r'facilities', r'buildings?', r'classrooms?']),
    ('laborator', [r'laborator(?:y|ies)', r'labs?']),
    ('administration', [r'administrat\w*', r'governance', r'organizational structure']),
]
_ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
_EXPLICIT_AREA = re.compile(r'\barea\s*[:\-]?\s*(x|ix|viii|vii|vi|iv|v|iii|ii|i|10|[1-9])\b', re.IGNORECASE)
# One passing mention does not make a document about a subject.
_AREA_MIN_HITS = 2


def _configured_areas():
    try:
        from qa_structure.models import AccreditationArea
        rows = list(AccreditationArea.objects.values_list('area_code', 'area_name'))
        return rows or _DEFAULT_AREAS
    except Exception:
        return _DEFAULT_AREAS


def detect_area_code(text_lower, filename=''):
    """
    Code of the configured accreditation area this text is about ('Area V'), or ''.

    An explicit "Area V" / "Area 5" in the text decides it. Otherwise each subject
    is scored by how often the text speaks of it, and the best-scoring subject
    wins if it is mentioned at least twice; the area is the configured one whose
    name carries that subject.
    """
    areas = _configured_areas()
    codes = {code.upper(): code for code, _name in areas}
    haystack = f'{(filename or "").lower()} {text_lower or ""}'

    explicit = _EXPLICIT_AREA.search(haystack)
    if explicit:
        token = explicit.group(1).upper()
        roman = _ROMAN[int(token) - 1] if token.isdigit() else token
        code = codes.get(f'AREA {roman}')
        if code:
            return code

    best, best_hits, best_pos = None, 0, None
    for subject, patterns in _AREA_TOPICS:
        hits, first = 0, None
        for pattern in patterns:
            for m in re.finditer(rf'\b{pattern}\b', haystack):
                hits += 1
                first = m.start() if first is None else min(first, m.start())
        if hits > best_hits or (hits == best_hits and hits and first < best_pos):
            best, best_hits, best_pos = subject, hits, first
    if not best or best_hits < _AREA_MIN_HITS:
        return ''
    for code, name in areas:
        if best in (name or '').lower():
            return code
    return ''


def extract_metadata_from_filename(filename):
    """Quick metadata extraction from filename only (fallback when no text extracted)."""
    metadata = {
        'title': '',
        'year': '',
        'document_type': 'Document',
        'qa_area': '',
        'criterion': '',
        'indicator': '',
        'description': '',
    }

    if filename:
        name = os.path.splitext(filename)[0]
        name = re.sub(r'[_\-\.]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        metadata['title'] = name.title()

        year_match = _years_in_name(filename)
        if year_match:
            metadata['year'] = year_match[-1]

    metadata['description'] = _fallback_description(
        title=metadata.get('title') or '',
        document_type=metadata.get('document_type') or '',
        filename=filename,
    )

    return metadata

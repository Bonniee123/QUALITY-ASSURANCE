"""
Resolving an accreditation area from what someone types into the message search.

Areas are stored with Roman codes -- ``Area I`` through ``Area X`` -- but nobody
types Roman numerals. People reach for the number ("Area 5", "area #5", or just
"5"), the Roman code, or the area's name ("Research"). All four have to land on
the same record.

Kept separate from ``views`` because it is pure text handling with no request in
sight, which makes it directly testable.
"""
import re

_ROMAN_VALUES = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
                 (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
                 (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]

# "area 5", "area #5", "area no. 5", "area-5", or a bare number.
_AREA_NUMBER = re.compile(
    r'^(?:area\s*)?(?:#|no\.?|number)?\s*(\d{1,2})$', re.IGNORECASE)
# "area v", "area  IX", or a bare Roman numeral.
_AREA_ROMAN = re.compile(
    r'^(?:area\s*)?(?:#|no\.?|number)?\s*([ivxlcdm]{1,7})$', re.IGNORECASE)


def to_roman(number: int) -> str:
    """5 -> 'V'. Used to turn a typed number into the stored area code."""
    if number <= 0:
        return ''
    out = []
    for value, glyph in _ROMAN_VALUES:
        while number >= value:
            out.append(glyph)
            number -= value
    return ''.join(out)


def _normalise(query: str) -> str:
    """Collapse whitespace and drop punctuation that only decorates the query."""
    return re.sub(r'\s+', ' ', query.replace('#', ' # ')).strip()


def area_codes_for(query: str) -> list:
    """
    Every area code the query could be naming, most specific first.

    Returns codes rather than model instances so this stays free of the database
    and can be reasoned about on its own. An empty list means the text does not
    look like an area reference at all, and the caller should fall back to
    searching names.
    """
    text = _normalise(query)
    if not text:
        return []

    compact = re.sub(r'\s*#\s*', ' ', text).strip()

    number_match = _AREA_NUMBER.match(compact)
    if number_match:
        roman = to_roman(int(number_match.group(1)))
        return [f'Area {roman}'] if roman else []

    roman_match = _AREA_ROMAN.match(compact)
    if roman_match:
        glyphs = roman_match.group(1).upper()
        # 'I' is a valid numeral but so is the pronoun; requiring the word
        # 'area' for a single letter avoids hijacking ordinary searches.
        bare = not re.match(r'^area\b', compact, re.IGNORECASE)
        if bare and len(glyphs) == 1:
            return []
        return [f'Area {glyphs}']

    return []


def looks_like_area_query(query: str) -> bool:
    """True when the text is a number or code reference rather than a name."""
    return bool(area_codes_for(query))

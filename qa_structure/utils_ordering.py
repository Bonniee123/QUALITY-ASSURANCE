"""
Ordering helpers for accreditation areas.

Area codes are Roman -- "Area I" through "Area X" -- and sorting them as text
puts Area X second, between Area I and Area II. These keys sort them the way a
reader expects.

This module previously also sorted the parameter, indicator and evidence levels
of the accreditation hierarchy. Those were removed as out of scope; only the
area key is still needed, by the repository's area filter.
"""
import re

_ROMAN_DIGITS = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def roman_to_int(text: str) -> int:
    """'IX' -> 9. Returns 0 for anything that is not a Roman numeral."""
    text = (text or '').strip().upper()
    if not text or any(ch not in _ROMAN_DIGITS for ch in text):
        return 0
    total = 0
    previous = 0
    for char in reversed(text):
        value = _ROMAN_DIGITS[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total


def area_roman_sort_key(area_code: str):
    """
    Sort key for an area code.

    Returns ``(0, number, code)`` for a recognised "Area <roman>" so the numeric
    order wins, and ``(1, 0, code)`` for anything else, which keeps unexpected
    codes together at the end instead of interleaving them.
    """
    code = (area_code or '').strip()
    match = re.match(r'^area\s+([IVXLCDM]+)$', code, re.IGNORECASE)
    if match:
        number = roman_to_int(match.group(1))
        if number:
            return (0, number, code.upper())
    return (1, 0, code.upper())

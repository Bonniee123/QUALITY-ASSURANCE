"""
Text near-duplicate detection, shared by every upload path.

One comparison, two callers. A single-file upload asks before saving, as it
always has. A bulk upload now asks after saving, in the background, once the
file's text has been extracted: extraction means OCR for images and scanned
PDFs, and running it inside the upload request is what held the browser on the
post-transfer wait for minutes while nothing had even been saved.

The verdict is the same from either caller -- the same threshold, the same
minimum length, the same exact prefilters, and the first stored document at or
above the threshold wins.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from django.conf import settings


def same_format_types(file_type: str) -> tuple:
    """
    The stored file types that are one format with this one.

    ".jpg" and ".jpeg" are two spellings of JPEG: the same bytes saved under
    each were not recognised as an exact copy, and were caught only as
    "visually similar". Every same-type comparison uses this.
    """
    return ('jpg', 'jpeg') if file_type in ('jpg', 'jpeg') else (file_type,)


def text_threshold() -> float:
    return float(getattr(settings, 'DUPLICATE_PREUPLOAD_TEXT_THRESHOLD', 0.97))


def min_text_chars() -> int:
    return int(getattr(settings, 'DUPLICATE_PREUPLOAD_MIN_TEXT_CHARS', 120))


def find_near_duplicate(candidate_text, candidates, text_for):
    """
    The first of ``candidates`` whose text is a near-duplicate of ``candidate_text``.

    Returns ``(candidate, ratio)``, or ``(None, 0.0)`` when nothing matches.
    ``text_for(candidate)`` supplies each candidate's text; a candidate with
    less than the minimum is skipped, exactly as before.
    """
    candidate_text = (candidate_text or '').strip()
    floor = min_text_chars()
    if len(candidate_text) < floor:
        return None, 0.0

    limit = text_threshold()
    candidate_len = len(candidate_text)
    matcher = SequenceMatcher(None)
    matcher.set_seq1(candidate_text)

    for candidate in candidates:
        existing = (text_for(candidate) or '').strip()
        existing_len = len(existing)
        if existing_len < floor:
            continue

        # SequenceMatcher.ratio() is 2*M/T, so it can never exceed
        # 2*min(len)/sum(len). When that ceiling is already under the threshold
        # the expensive comparison cannot possibly match -- skip it. This is
        # exact, not an approximation, so results are identical to comparing
        # every pair.
        ceiling = 2.0 * min(candidate_len, existing_len) / (candidate_len + existing_len)
        if ceiling < limit:
            continue

        matcher.set_seq2(existing)
        # quick_ratio() is an upper bound on ratio() computed from character
        # counts alone -- another exact prefilter that avoids the O(n*m) block
        # matching.
        if matcher.quick_ratio() < limit:
            continue
        ratio = matcher.ratio()
        if ratio >= limit:
            return candidate, ratio
    return None, 0.0

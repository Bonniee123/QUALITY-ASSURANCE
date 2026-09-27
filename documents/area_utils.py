"""Shared helpers for document area display and filtering."""
from django.db.models import Q


def document_area_code(doc) -> str:
    """Canonical area code for display and filtering (FK wins when set)."""
    acc = getattr(doc, 'acc_area', None)
    if acc is not None and getattr(acc, 'area_code', None):
        return acc.area_code
    return (getattr(doc, 'qa_area', None) or '').strip()


def document_area_name(doc) -> str:
    """Human-readable area name aligned with document_area_code()."""
    acc = getattr(doc, 'acc_area', None)
    code = document_area_code(doc)
    if acc is not None and acc.area_code == code:
        return (getattr(acc, 'area_name', None) or '').strip()
    qa = (getattr(doc, 'qa_area', None) or '').strip()
    if qa and ' — ' in qa:
        return qa.split(' — ', 1)[1].strip()
    if qa and ' - ' in qa:
        return qa.split(' - ', 1)[1].strip()
    if code:
        from qa_structure.models import AccreditationArea
        return (
            AccreditationArea.objects.filter(area_code=code)
            .values_list('area_name', flat=True)
            .first()
            or ''
        ).strip()
    return ''


def build_area_filter_q(area_codes):
    """
    Match documents in the given area(s).

    When acc_area is set (faculty upload / confirmed mapping), it is authoritative.
    qa_area is only used for filtering when acc_area is unset (legacy / free-text).
    """
    codes = [c for c in (area_codes or []) if c]
    if not codes:
        return Q()
    return Q(acc_area__area_code__in=codes) | Q(acc_area__isnull=True, qa_area__in=codes)

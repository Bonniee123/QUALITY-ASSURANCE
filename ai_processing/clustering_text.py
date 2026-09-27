"""Text preparation for document clustering (separate from keyword extraction)."""


def clustering_input_text(doc) -> str:
    """Build rich, weighted text for clustering features."""
    title = (doc.title or '').strip()
    parts = []
    if title:
        parts.extend([title] * 3)
    for field in (doc.description, doc.document_type, doc.criterion, doc.indicator):
        val = (field or '').strip()
        if val:
            parts.append(val)
    body = (doc.combined_text or '').strip()
    if body:
        parts.append(body)
    base = ' '.join(parts)
    dtype = (doc.document_type or '').strip().lower()
    if dtype:
        base += f' {dtype} {dtype} {dtype}'
    if doc.year:
        base += f' year_{doc.year}'
    return base or title or 'empty document'

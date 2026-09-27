"""
Smart recommendation service.
Generates document recommendations from cluster neighbors, duplicates, and keywords.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def clip_automap_text(text):
    """Avoid multi‑MB OCR/extracted bodies freezing TF-IDF."""
    if text is None:
        return ''
    s = str(text)
    limit = int(getattr(settings, 'AUTOMAP_MAX_TEXT_CHARS', 24000))
    if len(s) <= limit:
        return s
    return s[:limit]


def generate_document_recommendation(document, cluster_docs):
    """
    Generate recommendation text for a document based on its cluster neighbors.

    Args:
        document: Document model instance
        cluster_docs: QuerySet of documents in the same cluster

    Returns:
        str: Recommendation text
    """
    recommendations = []

    # Check duplicates
    if document.duplicate_status == 'possible':
        recommendations.append(
            "This document has been flagged as a possible duplicate. "
            "Please review similar documents and confirm if this is unique."
        )

    # Cluster-based recommendation
    if cluster_docs and cluster_docs.count() > 1:
        other_docs = cluster_docs.exclude(pk=document.pk)[:5]
        if other_docs:
            titles = ', '.join([d.title for d in other_docs])
            recommendations.append(
                f"This document is grouped with similar documents: {titles}. "
                "These may cover related QA areas."
            )

    # Keyword-based recommendation
    if document.tfidf_keywords:
        keywords = [k[0] if isinstance(k, (list, tuple)) else k for k in document.tfidf_keywords[:5]]
        recommendations.append(
            f"Key topics identified: {', '.join(keywords)}."
        )

    if not recommendations:
        recommendations.append("No specific recommendations at this time.")

    return ' '.join(recommendations)

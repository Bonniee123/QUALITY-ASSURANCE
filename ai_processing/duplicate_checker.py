"""
Duplicate document detection using cosine similarity on TF-IDF vectors.
"""
import logging
import math
import re

from django.conf import settings

logger = logging.getLogger(__name__)


def duplicate_threshold():
    """Configurable cosine similarity threshold for duplicate flagging."""
    return float(getattr(settings, 'DUPLICATE_SIMILARITY_THRESHOLD', 0.85))


def check_duplicate_documents(tfidf_matrix, doc_index, threshold=None):
    """
    Check if a document is similar to any existing documents.

    Args:
        tfidf_matrix: TF-IDF sparse matrix for all documents
        doc_index: Index of the document to check
        threshold: Cosine similarity threshold for duplicate flagging

    Returns:
        list of dicts: [{'index': int, 'similarity': float}, ...]
        Only includes documents above the threshold (excluding self).
    """
    if tfidf_matrix is None or doc_index >= tfidf_matrix.shape[0]:
        return []
    threshold = duplicate_threshold() if threshold is None else float(threshold)

    try:
        # Compute cosine similarity of target doc vs all docs
        from sklearn.metrics.pairwise import cosine_similarity
        doc_vector = tfidf_matrix[doc_index]
        similarities = cosine_similarity(doc_vector, tfidf_matrix).flatten()

        duplicates = []
        for i, sim in enumerate(similarities):
            if i != doc_index and sim >= threshold:
                duplicates.append({
                    'index': i,
                    'similarity': round(float(sim), 4),
                })

        # Sort by similarity (highest first)
        duplicates.sort(key=lambda x: x['similarity'], reverse=True)
        return duplicates

    except Exception as e:
        logger.error(f"Duplicate checking error: {e}")
        return []


def check_all_duplicates(tfidf_matrix, threshold=None):
    """
    Check all documents for duplicates and return a mapping.

    Returns:
        dict: {doc_index: [{'index': int, 'similarity': float}, ...], ...}
    """
    if tfidf_matrix is None:
        return {}
    threshold = duplicate_threshold() if threshold is None else float(threshold)

    try:
        from sklearn.metrics.pairwise import cosine_similarity
        sim_matrix = cosine_similarity(tfidf_matrix)
        result = {}

        for i in range(sim_matrix.shape[0]):
            duplicates = []
            for j in range(sim_matrix.shape[1]):
                if i != j and sim_matrix[i][j] >= threshold:
                    duplicates.append({
                        'index': j,
                        'similarity': round(float(sim_matrix[i][j]), 4),
                    })
            if duplicates:
                duplicates.sort(key=lambda x: x['similarity'], reverse=True)
                result[i] = duplicates

        return result

    except Exception as e:
        logger.error(f"Bulk duplicate checking error: {e}")
        return {}


# --- Verifying a candidate against the documents as they are written ---------
#
# The matrix above is built from `clean_text`, which deletes every standalone
# number. That is the right preprocessing for clustering and for keywords -- you
# do not want "2026" as a top term -- but it is the wrong one for deciding
# whether two documents are the same document, because in a generated report the
# numbers *are* the content.
#
# Measured on this archive: three "Dashboard Summary" exports reporting 22, 18
# and 16 documents, generated on three different dates, are identical once the
# digits are stripped, so cosine over them is exactly 1.0000. The panel showed
# them to a reader as a near-perfect match between files that plainly say
# different things. The error runs the other way too: the manuscript (#569) and
# its PDF (#612) scored 0.8587 on the stripped text and 0.9752 on the real text,
# so a genuine pair looked like a borderline coincidence.
#
# So a candidate the matrix proposes is confirmed here, against the text as
# written, before it is recorded as a match.

_WORD_RE = re.compile(r'[a-z0-9]+')


def word_frequencies(text):
    """How often each word occurs in the text as written, digits included."""
    counts = {}
    for word in _WORD_RE.findall((text or '').lower()):
        counts[word] = counts.get(word, 0) + 1
    return counts


def frequency_agreement(freq_a, freq_b):
    """
    Cosine similarity of two word-frequency vectors, in [0.0, 1.0].

    Same measure as the detector uses -- cosine over term vectors -- so the
    number on screen and the number that raised the flag are the same kind of
    thing. It is computed over the two documents alone, with no corpus-wide
    pruning, which is what makes it checkable: a reader can open both files and
    see the wording the percentage is claiming.
    """
    if not freq_a or not freq_b:
        return 0.0
    shared = sum(freq_a[w] * freq_b[w] for w in set(freq_a) & set(freq_b))
    if not shared:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in freq_a.values()))
    norm_b = math.sqrt(sum(v * v for v in freq_b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return min(1.0, shared / (norm_a * norm_b))


def text_agreement(text_a, text_b):
    """How much of the wording two documents actually share, in [0.0, 1.0]."""
    return frequency_agreement(word_frequencies(text_a), word_frequencies(text_b))

"""
Build clustering feature matrices: TF-IDF (+ QA stopwords), hybrid metadata, optional embeddings.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_embedding_model = None


def build_clustering_matrix(documents, cluster_texts):
    """
    Build the matrix used for smart clustering.

    Returns (matrix, feature_names, backend) where backend is
    'embedding', 'hybrid', or 'tfidf'.
    """
    from ai_processing.tfidf_service import compute_tfidf_matrix

    use_embeddings = bool(getattr(settings, 'AI_CLUSTER_USE_EMBEDDINGS', False))
    if use_embeddings:
        from ai_processing.embedding_service import compute_embedding_matrix
        emb = compute_embedding_matrix(documents)
        if emb is not None:
            return emb, [], 'embedding'

    tfidf_matrix, feature_names = compute_tfidf_matrix(
        cluster_texts,
        use_qa_stopwords=True,
    )
    if tfidf_matrix is None:
        return None, [], 'tfidf'

    if bool(getattr(settings, 'AI_CLUSTER_HYBRID_METADATA', True)):
        meta_matrix = _build_metadata_matrix(documents)
        if meta_matrix is not None:
            from scipy.sparse import hstack
            weight = float(getattr(settings, 'AI_CLUSTER_METADATA_WEIGHT', 1.5))
            tfidf_matrix = hstack([tfidf_matrix, meta_matrix.multiply(weight)])
            return tfidf_matrix, feature_names, 'hybrid'

    return tfidf_matrix, feature_names, 'tfidf'


def _build_metadata_matrix(documents):
    """One-hot encode document type and year for hybrid clustering."""
    if not documents:
        return None
    try:
        from sklearn.preprocessing import OneHotEncoder
        from scipy.sparse import hstack, csr_matrix
        import numpy as np

        types = [[(doc.document_type or 'Unknown').strip()[:80]] for doc in documents]
        years = [[int(doc.year)] if doc.year else [0] for doc in documents]

        type_enc = OneHotEncoder(handle_unknown='ignore', sparse_output=True)
        year_enc = OneHotEncoder(handle_unknown='ignore', sparse_output=True)
        type_mat = type_enc.fit_transform(types)
        year_mat = year_enc.fit_transform(years)
        return hstack([type_mat, year_mat]).tocsr()
    except Exception as exc:
        logger.warning('Metadata feature matrix failed: %s', exc)
        return None

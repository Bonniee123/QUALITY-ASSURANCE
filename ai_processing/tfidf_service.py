"""
TF-IDF keyword extraction service.
Uses scikit-learn TfidfVectorizer to identify important keywords per document.
"""
import logging
from .text_cleaning import clean_text

logger = logging.getLogger(__name__)


def compute_tfidf_keywords(documents_text, top_n=10):
    """
    Compute TF-IDF on a corpus and extract top keywords per document.

    Args:
        documents_text: List of text strings (one per document)
        top_n: Number of top keywords to extract per document

    Returns:
        tfidf_matrix: Sparse TF-IDF matrix
        feature_names: List of all feature (word) names
        keywords_per_doc: List of lists, each containing (keyword, score) tuples
    """
    if not documents_text or all(not t.strip() for t in documents_text):
        logger.warning("No valid text found for TF-IDF computation.")
        return None, [], []

    # Clean all texts
    cleaned = [clean_text(t) for t in documents_text]

    # Filter out empty texts — replace with placeholder
    cleaned = [t if t.strip() else 'empty document' for t in cleaned]

    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        n_docs = len(cleaned)
        max_df = 1.0 if n_docs < 5 else 0.95
        vectorizer = TfidfVectorizer(
            max_features=5000,
            min_df=1,
            max_df=max_df,
            stop_words='english',
            ngram_range=(1, 2),  # Unigrams and bigrams
        )
        tfidf_matrix = vectorizer.fit_transform(cleaned)
        feature_names = vectorizer.get_feature_names_out()

        # Extract top keywords per document
        keywords_per_doc = []
        for i in range(tfidf_matrix.shape[0]):
            row = tfidf_matrix[i].toarray().flatten()
            top_indices = row.argsort()[-top_n:][::-1]
            top_keywords = [
                (feature_names[idx], round(float(row[idx]), 4))
                for idx in top_indices if row[idx] > 0
            ]
            keywords_per_doc.append(top_keywords)

        return tfidf_matrix, feature_names, keywords_per_doc

    except Exception as e:
        logger.error(f"TF-IDF computation error: {e}")
        return None, [], []


def compute_tfidf_matrix(documents_text, *, ngram_range=(1, 2), use_qa_stopwords=False):
    """
    Build a TF-IDF matrix for clustering (no per-document keyword extraction).
    Returns (matrix, feature_names) or (None, []).
    """
    if not documents_text or all(not t.strip() for t in documents_text):
        logger.warning("No valid text found for TF-IDF matrix.")
        return None, []

    cleaned = [clean_text(t) for t in documents_text]
    cleaned = [t if t.strip() else 'empty document' for t in cleaned]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        if use_qa_stopwords:
            from ai_processing.qa_stopwords import clustering_stop_words
            stop_words = clustering_stop_words()
        else:
            stop_words = 'english'
        n_docs = len(cleaned)
        max_df = 1.0 if n_docs < 5 else 0.95
        vectorizer = TfidfVectorizer(
            max_features=5000,
            min_df=1,
            max_df=max_df,
            stop_words=stop_words,
            ngram_range=ngram_range,
        )
        tfidf_matrix = vectorizer.fit_transform(cleaned)
        feature_names = vectorizer.get_feature_names_out()
        return tfidf_matrix, feature_names

    except Exception as e:
        logger.error(f"TF-IDF matrix error: {e}")
        return None, []

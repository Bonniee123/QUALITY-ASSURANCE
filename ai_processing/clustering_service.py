"""
K-Means clustering service for grouping similar documents.
"""
import logging

logger = logging.getLogger(__name__)


def run_kmeans_clustering(tfidf_matrix, n_clusters, feature_names=None):
    """
    Cluster documents using K-Means on TF-IDF vectors.

    Args:
        tfidf_matrix: TF-IDF sparse matrix
        n_clusters: Number of clusters to create
        feature_names: Optional list of feature names for top term extraction

    Returns:
        dict with:
            'labels': list of cluster labels (one per document)
            'cluster_centers': numpy array of centroids
            'top_terms_per_cluster': dict mapping cluster_id to top terms
    """
    if tfidf_matrix is None or tfidf_matrix.shape[0] < n_clusters:
        logger.warning("Not enough documents for clustering.")
        return {'labels': [], 'cluster_centers': None, 'top_terms_per_cluster': {}}

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        kmeans = KMeans(
            n_clusters=n_clusters,
            random_state=42,
            n_init=10,
            max_iter=300,
        )
        kmeans.fit(tfidf_matrix)

        labels = kmeans.labels_.tolist()

        # Extract top terms per cluster if feature names provided
        top_terms = {}
        if feature_names is not None and len(feature_names) > 0:
            order_centroids = kmeans.cluster_centers_.argsort()[:, ::-1]
            for i in range(n_clusters):
                terms = []
                for idx in order_centroids[i, :8]:  # Top 8 terms per cluster
                    if idx < len(feature_names):
                        terms.append(str(feature_names[idx]))
                top_terms[i] = terms

        return {
            'labels': labels,
            'cluster_centers': kmeans.cluster_centers_,
            'top_terms_per_cluster': top_terms,
        }

    except Exception as e:
        logger.error(f"K-Means clustering error: {e}")
        return {'labels': [], 'cluster_centers': None, 'top_terms_per_cluster': {}}

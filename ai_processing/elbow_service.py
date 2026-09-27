"""
Elbow Method service for determining optimal number of K-Means clusters.
Tests a range of k values and computes inertia to find the elbow point.
"""
import logging

logger = logging.getLogger(__name__)


def run_elbow_method(tfidf_matrix, k_range=None):
    """
    Run the Elbow Method to find the optimal number of clusters.

    Args:
        tfidf_matrix: TF-IDF sparse matrix from the vectorizer
        k_range: Range of k values to test (default: 2 to min(10, n_samples))

    Returns:
        dict with:
            'k_values': list of k values tested
            'inertias': list of inertia values
            'optimal_k': suggested optimal k
    """
    if tfidf_matrix is None or tfidf_matrix.shape[0] < 2:
        logger.warning("Not enough documents for Elbow Method.")
        return {'k_values': [], 'inertias': [], 'optimal_k': 2}

    n_samples = tfidf_matrix.shape[0]
    max_k = min(10, n_samples)

    if k_range is None:
        k_range = range(2, max_k + 1)
    else:
        k_range = range(max(2, k_range[0]), min(max_k + 1, k_range[-1] + 1))

    k_values = list(k_range)
    inertias = []

    for k in k_values:
        try:
            from sklearn.cluster import KMeans
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
            kmeans.fit(tfidf_matrix)
            inertias.append(float(kmeans.inertia_))
        except Exception as e:
            logger.error(f"KMeans error for k={k}: {e}")
            inertias.append(0)

    # Find elbow point using the maximum second derivative (kneedle-like)
    optimal_k = find_elbow_point(k_values, inertias)

    return {
        'k_values': k_values,
        'inertias': inertias,
        'optimal_k': optimal_k,
    }


def find_elbow_point(k_values, inertias):
    """
    Find the elbow point from k-values and inertia using the angle method.
    Returns the optimal k value.
    """
    if len(k_values) < 3:
        return k_values[0] if k_values else 2

    # Compute second derivative to find the steepest change
    import numpy as np
    diffs = np.diff(inertias)
    diffs2 = np.diff(diffs)

    if len(diffs2) > 0:
        # The elbow is where the second derivative is maximized (least negative becomes most positive change).
        # diffs2[j] = I[j] - 2*I[j+1] + I[j+2] is the curvature at k_values[j+1], so
        # the offset is 1; it was 2, which reported the k one past the elbow.
        elbow_idx = np.argmax(diffs2) + 1
        if elbow_idx < len(k_values):
            return k_values[elbow_idx]

    # Fallback: return middle value
    return k_values[len(k_values) // 2]

"""
Area- and type-aware document clustering with silhouette / Davies–Bouldin k selection,
post-cluster merging, and descriptive auto-labels.
"""
import logging
from collections import Counter, defaultdict

from django.conf import settings

from ai_processing.clustering_text import clustering_input_text

logger = logging.getLogger(__name__)

__all__ = ['clustering_input_text', 'group_documents_by_area', 'run_smart_clustering']


def group_documents_by_area(documents):
    """Backward-compatible wrapper — groups by area only."""
    from documents.area_utils import document_area_code

    groups = defaultdict(list)
    for idx, doc in enumerate(documents):
        area = document_area_code(doc) or 'Unassigned'
        groups[area].append((idx, doc))
    return dict(groups)


def group_documents_for_clustering(documents):
    """
    Group documents for clustering.
    Default: separate by accreditation area AND document type.
    """
    from documents.area_utils import document_area_code

    within_area = bool(getattr(settings, 'AI_CLUSTER_WITHIN_AREA', True))
    within_type = bool(getattr(settings, 'AI_CLUSTER_WITHIN_DOC_TYPE', True))

    groups = defaultdict(list)
    for idx, doc in enumerate(documents):
        if not within_area:
            groups['All'].append((idx, doc))
            continue
        area = document_area_code(doc) or 'Unassigned'
        if within_type:
            dtype = (doc.document_type or 'Unknown').strip()
            key = f'{area}\0{dtype}'
        else:
            key = area
        groups[key].append((idx, doc))
    return dict(groups)


def _group_area_code(group_key):
    if group_key == 'All':
        return 'All'
    if '\0' in group_key:
        return group_key.split('\0', 1)[0]
    return group_key


def _group_doc_type(group_key):
    if '\0' in group_key:
        return group_key.split('\0', 1)[1]
    return ''


def _group_display_name(group_key):
    """'Area III · Report' for a group key; 'All documents' when groups are not split."""
    if group_key == 'All':
        return 'All documents'
    return ' · '.join(part for part in (_group_area_code(group_key), _group_doc_type(group_key)) if part)


def _matrix_rows(matrix, indices):
    return matrix[indices]


def _pair_similarity(sub_matrix):
    from sklearn.metrics.pairwise import cosine_similarity
    if hasattr(sub_matrix, 'toarray'):
        a = sub_matrix[0:1].toarray()
        b = sub_matrix[1:2].toarray()
    else:
        a = sub_matrix[0:1]
        b = sub_matrix[1:2]
    return float(cosine_similarity(a, b)[0, 0])


def _dense_matrix(matrix):
    if hasattr(matrix, 'toarray'):
        return matrix.toarray()
    return matrix


def choose_cluster_count(matrix, n_samples):
    """Pick k using silhouette + Davies–Bouldin, falling back to elbow."""
    return choose_cluster_count_and_method(matrix, n_samples)[0]


def choose_cluster_count_and_method(matrix, n_samples):
    """
    k, and what chose it: 'silhouette' when the silhouette / Davies–Bouldin
    score found a k that separates the group, 'elbow' when it fell back.
    """
    if n_samples <= 1:
        return 1, 'size'
    if n_samples == 2:
        return 1, 'size'

    max_k = min(
        int(getattr(settings, 'AI_CLUSTER_MAX_K', 8)),
        max(2, n_samples // 2),
        n_samples - 1,
    )
    min_silhouette = float(getattr(settings, 'AI_CLUSTER_MIN_SILHOUETTE', 0.08))

    best_k = 2
    best_score = -999.0
    best_silhouette = -1.0
    used_metric = False
    use_dense_db = n_samples <= int(getattr(settings, 'AI_CLUSTER_DAVIES_MAX_SAMPLES', 500))

    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import davies_bouldin_score, silhouette_score

        dense = _dense_matrix(matrix) if use_dense_db else None

        for k in range(2, max_k + 1):
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
            labels = kmeans.fit_predict(matrix)
            if len(set(labels)) < 2:
                continue
            sil = float(silhouette_score(matrix, labels, metric='cosine'))
            if dense is not None:
                db = float(davies_bouldin_score(dense, labels))
                score = sil - (db / 10.0)
            else:
                score = sil
            used_metric = True
            if score > best_score:
                best_score = score
                best_silhouette = sil
                best_k = k
    except Exception as exc:
        logger.warning('Composite k-selection failed: %s', exc)

    if used_metric and best_silhouette >= min_silhouette:
        return best_k, 'silhouette'

    from ai_processing.elbow_service import run_elbow_method
    return run_elbow_method(matrix)['optimal_k'], 'elbow'


def merge_similar_local_clusters(local_labels, sub_matrix):
    """Merge clusters whose centroids exceed AI_CLUSTER_MERGE_SIMILARITY."""
    threshold = float(getattr(settings, 'AI_CLUSTER_MERGE_SIMILARITY', 0.7))
    labels = list(local_labels)
    unique = sorted(set(labels))
    if len(unique) < 2:
        return labels

    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        dense = _dense_matrix(sub_matrix)
        centroids = {}
        for lid in unique:
            rows = dense[[i for i, lab in enumerate(labels) if lab == lid]]
            centroids[lid] = rows.mean(axis=0)

        parent = {lid: lid for lid in unique}

        def find(node):
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for i, a in enumerate(unique):
            for b in unique[i + 1:]:
                sim = float(cosine_similarity([centroids[a]], [centroids[b]])[0, 0])
                if sim >= threshold:
                    parent[find(b)] = find(a)

        remap_raw = {lid: find(lid) for lid in unique}
        canonical = {val: idx for idx, val in enumerate(sorted(set(remap_raw.values())))}
        return [canonical[remap_raw[lid]] for lid in labels]
    except Exception as exc:
        logger.warning('Cluster merge pass failed: %s', exc)
        return labels


def build_cluster_display_label(area_code, top_terms, doc_types, sample_title=None):
    parts = []
    if area_code and area_code != 'All' and area_code != 'Unassigned':
        parts.append(area_code)
    if doc_types:
        common = Counter(doc_types).most_common(1)
        if common and common[0][0]:
            parts.append(common[0][0])
    terms = [str(t) for t in (top_terms or [])[:3] if t]
    if terms:
        parts.append(', '.join(terms))
    if sample_title:
        # The card used to show this label on one clipped line, so 42 characters
        # was already more than it could display and the cap cost nothing. The
        # card now gives the example two lines at about sixty characters, and
        # several of these titles ("DEVELOPMENT OF AN ONLINE ARCHIVING
        # SYSTEM...") only begin to distinguish themselves past the old cut.
        short = sample_title.strip()
        if len(short) > 64:
            short = short[:61] + '...'
        parts.append(f'eg. {short}')
    return ' · '.join(parts) if parts else 'Mixed documents'


def _assign_singleton_cluster(global_labels, cluster_meta, next_global_id, idx, doc, area_code):
    gid = next_global_id
    cluster_meta[gid] = {
        'display_label': build_cluster_display_label(
            area_code, [], [doc.document_type], sample_title=doc.title
        ),
        'top_terms': [],
        'area_code': area_code,
        'size': 1,
    }
    global_labels[idx] = gid
    return gid + 1


def _top_terms_for_labels(local_labels, sub_matrix, feature_names, top_n=8):
    """Extract top TF-IDF terms per cluster label after merging."""
    if feature_names is None or len(feature_names) == 0:
        return {}
    try:
        import numpy as np

        dense = _dense_matrix(sub_matrix)
        terms = {}
        for lid in sorted(set(local_labels)):
            rows = dense[[i for i, lab in enumerate(local_labels) if lab == lid]]
            if rows.size == 0:
                terms[lid] = []
                continue
            centroid = rows.mean(axis=0)
            if len(centroid) > len(feature_names):
                centroid = centroid[: len(feature_names)]
            top_idx = centroid.argsort()[-top_n:][::-1]
            terms[lid] = [
                str(feature_names[i]) for i in top_idx if i < len(feature_names) and centroid[i] > 0
            ][:top_n]
        return terms
    except Exception as exc:
        logger.warning('Top term extraction failed: %s', exc)
        return {}


def run_smart_clustering(documents, cluster_matrix, feature_names):
    """
    Cluster documents within accreditation area (+ document type by default).

    Returns labels, cluster_meta, elbow_summary, total_clusters.
    """
    from ai_processing.clustering_service import run_kmeans_clustering
    from ai_processing.elbow_service import run_elbow_method

    n_docs = len(documents)
    if cluster_matrix is None or n_docs == 0:
        return {'labels': [], 'cluster_meta': {}, 'elbow_summary': None, 'total_clusters': 0}

    pair_threshold = float(getattr(settings, 'AI_CLUSTER_PAIR_SIMILARITY', 0.35))
    global_labels = [None] * n_docs
    cluster_meta = {}
    next_global_id = 0
    elbow_summary = None
    elbow_group_key = None
    largest_group_size = 0

    groups = group_documents_for_clustering(documents)

    for group_key in sorted(groups.keys()):
        area_code = _group_area_code(group_key)
        index_doc_pairs = groups[group_key]
        indices = [i for i, _ in index_doc_pairs]
        docs_in_group = [doc for _, doc in index_doc_pairs]
        sub_matrix = _matrix_rows(cluster_matrix, indices)
        n = len(indices)

        if n > largest_group_size:
            largest_group_size = n
            if n >= 2:
                # The Elbow chart describes this one group -- the largest -- so
                # it says which group it is, and (below) which k that group was
                # actually given and by what: usually the silhouette score, which
                # can disagree with the elbow.
                elbow_summary = run_elbow_method(sub_matrix)
                elbow_summary['group'] = _group_display_name(group_key)
                elbow_summary['group_size'] = n
                elbow_group_key = group_key

        if n == 1:
            next_global_id = _assign_singleton_cluster(
                global_labels, cluster_meta, next_global_id, indices[0], docs_in_group[0], area_code
            )
            continue

        if n == 2:
            sim = _pair_similarity(sub_matrix)
            if sim >= pair_threshold:
                gid = next_global_id
                next_global_id += 1
                for idx in indices:
                    global_labels[idx] = gid
                cluster_meta[gid] = {
                    'display_label': build_cluster_display_label(
                        area_code,
                        [],
                        [d.document_type for d in docs_in_group],
                        sample_title=docs_in_group[0].title,
                    ),
                    'top_terms': [],
                    'area_code': area_code,
                    'size': 2,
                }
            else:
                for idx in indices:
                    doc = documents[idx]
                    next_global_id = _assign_singleton_cluster(
                        global_labels, cluster_meta, next_global_id, idx, doc, area_code
                    )
            continue

        k, k_method = choose_cluster_count_and_method(sub_matrix, n)
        k = max(1, min(k, n))
        result = run_kmeans_clustering(sub_matrix, k, feature_names)
        local_labels = result.get('labels') or []
        if group_key == elbow_group_key:
            elbow_summary['chosen_k'] = k
            elbow_summary['k_method'] = k_method
        if not local_labels:
            gid = next_global_id
            next_global_id += 1
            for idx in indices:
                global_labels[idx] = gid
            cluster_meta[gid] = {
                'display_label': build_cluster_display_label(area_code, [], [], sample_title=''),
                'top_terms': [],
                'area_code': area_code,
                'size': n,
            }
            continue

        if len(set(local_labels)) > 1:
            local_labels = merge_similar_local_clusters(local_labels, sub_matrix)
        if group_key == elbow_group_key:
            elbow_summary['formed'] = len(set(local_labels))

        merged_top_terms = _top_terms_for_labels(local_labels, sub_matrix, feature_names)
        if not merged_top_terms:
            merged_top_terms = result.get('top_terms_per_cluster') or {}

        local_to_global = {}
        for local_id in sorted(set(local_labels)):
            local_to_global[local_id] = next_global_id
            next_global_id += 1

        for pos, doc_idx in enumerate(indices):
            local_id = local_labels[pos]
            global_labels[doc_idx] = local_to_global[local_id]

        for local_id, gid in local_to_global.items():
            member_indices = [indices[pos] for pos, lid in enumerate(local_labels) if lid == local_id]
            member_docs = [documents[i] for i in member_indices]
            top_terms = merged_top_terms.get(local_id, [])
            cluster_meta[gid] = {
                'display_label': build_cluster_display_label(
                    area_code,
                    top_terms,
                    [d.document_type for d in member_docs],
                    sample_title=member_docs[0].title if member_docs else None,
                ),
                'top_terms': top_terms,
                'area_code': area_code,
                'size': len(member_indices),
            }

    return {
        'labels': global_labels,
        'cluster_meta': cluster_meta,
        'elbow_summary': elbow_summary,
        'total_clusters': len(cluster_meta),
    }

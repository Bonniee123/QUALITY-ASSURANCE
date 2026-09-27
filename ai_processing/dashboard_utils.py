"""Context helpers for the admin AI Processing dashboard."""
from django.conf import settings
from django.db.models import Count, Max, Q

from documents.models import ClusterResult, Document


def get_clustering_engine_info(request=None):
    """
    Describe how the clusters on screen were made, for the admin UI.

    The latest clustering run's own record comes first, whoever started it. A
    run after an upload happens in the background, with no session to write
    to, so this used to fall back to the settings and say "Semantic embeddings"
    even for a run that had used TF-IDF because the PC was short of memory.
    With no run recorded yet, it describes what the settings will use.
    """
    from documents.ai_pipeline import CLUSTERING_METHODS, last_clustering_method

    backend = last_clustering_method()
    if not backend and request is not None:
        backend = (request.session.get('ai_cluster_backend') or '').strip()
    if backend not in CLUSTERING_METHODS:
        if bool(getattr(settings, 'AI_CLUSTER_USE_EMBEDDINGS', False)):
            backend = 'embedding'
        elif getattr(settings, 'AI_CLUSTER_HYBRID_METADATA', True):
            backend = 'hybrid'
        else:
            backend = 'tfidf'

    if backend == 'embedding':
        return {
            'mode': 'embedding',
            'label': 'Semantic embeddings',
            'description': 'Documents are grouped by meaning using sentence-transformer vectors, then area and document-type rules.',
            'badge_class': 'badge-complete',
            'icon': 'bi-stars',
        }
    if backend == 'hybrid':
        return {
            'mode': 'hybrid',
            'label': 'Hybrid TF-IDF + metadata',
            'description': 'Keyword vectors plus document type and year, clustered within each area and document type.',
            'badge_class': 'badge-suggested',
            'icon': 'bi-layers',
        }
    return {
        'mode': 'tfidf',
        'label': 'TF-IDF keywords',
        'description': 'Classic keyword-based clustering with QA stopwords and area-aware grouping.',
        'badge_class': 'badge-unmapped',
        'icon': 'bi-fonts',
    }


def get_pipeline_settings_summary():
    """Short list of clustering settings for the admin panel."""
    return [
        {
            'label': 'Within area',
            'enabled': bool(getattr(settings, 'AI_CLUSTER_WITHIN_AREA', True)),
        },
        {
            'label': 'Within document type',
            'enabled': bool(getattr(settings, 'AI_CLUSTER_WITHIN_DOC_TYPE', True)),
        },
        {
            'label': 'Hybrid metadata',
            'enabled': bool(getattr(settings, 'AI_CLUSTER_HYBRID_METADATA', True)),
        },
        {
            'label': 'Semantic embeddings',
            'enabled': bool(getattr(settings, 'AI_CLUSTER_USE_EMBEDDINGS', False)),
        },
    ]


def build_cluster_summaries():
    """Cluster cards: number, descriptive label, count, top keywords."""
    dist = (
        Document.objects.filter(is_archived=False)
        .exclude(cluster_label__isnull=True)
        .values('cluster_label')
        .annotate(count=Count('id'), last=Max('uploaded_at'))
        .order_by('cluster_label')
    )
    label_by_num = {}
    keywords_by_num = {}
    for cr in ClusterResult.objects.order_by('-created_at').values(
        'cluster_number', 'cluster_label', 'top_keywords'
    ):
        if cr['cluster_number'] not in label_by_num:
            label_by_num[cr['cluster_number']] = cr['cluster_label'] or ''
        if cr['cluster_number'] not in keywords_by_num and cr['top_keywords']:
            keywords_by_num[cr['cluster_number']] = cr['top_keywords'][:6]

    summaries = []
    for row in dist:
        num = row['cluster_label']
        summaries.append({
            'number': num,
            'label': label_by_num.get(num) or f'Cluster {num}',
            'count': row['count'],
            'keywords': keywords_by_num.get(num, []),
            'last_upload': row['last'],
        })
    return summaries


def get_ai_processing_stats():
    """Aggregate counts for dashboard stat cards."""
    base = Document.objects.filter(is_archived=False)
    return {
        'total_count': base.count(),
        'processed_count': base.filter(is_processed=True).count(),
        'unclustered_count': base.filter(cluster_label__isnull=True).count(),
        'dup_review_count': base.filter(
            duplicate_status__in=('possible', 'pending_check', 'confirmed_dup')
        ).count(),
        'pending_count': base.filter(is_processed=False).count(),
        'cluster_count': base.exclude(cluster_label__isnull=True).values('cluster_label').distinct().count(),
    }


def cluster_label_map():
    """Map cluster_number -> latest descriptive label."""
    labels = {}
    for cr in ClusterResult.objects.order_by('-created_at').values('cluster_number', 'cluster_label'):
        labels.setdefault(cr['cluster_number'], cr['cluster_label'] or f"Cluster {cr['cluster_number']}")
    return labels


def filter_documents_queryset(queryset, filter_key):
    """Apply list filter: all, review, unclustered, pending."""
    key = (filter_key or 'all').strip().lower()
    if key == 'review':
        return queryset.filter(duplicate_status__in=('possible', 'pending_check', 'confirmed_dup'))
    if key == 'unclustered':
        return queryset.filter(cluster_label__isnull=True)
    if key == 'pending':
        return queryset.filter(is_processed=False)
    return queryset

"""
Views for the AI Processing page.
Allows viewing AI results and triggering reprocessing of documents.
"""
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from documents.models import Document, ClusterResult, ActivityLog
from accounts.decorators import admin_required
from documents.ai_pipeline import run_full_ai_pipeline
from documents.jobs import enqueue_job
from documents.models import BackgroundJob

from .dashboard_utils import (
    build_cluster_summaries,
    cluster_label_map,
    filter_documents_queryset,
    get_ai_processing_stats,
    get_clustering_engine_info,
)

AI_LIST_PAGE_SIZE = 25
AI_CLUSTER_PREVIEW = 4


@login_required
@admin_required
def ai_processing_list(request):
    """Show all documents with their AI processing results and stats."""
    stats = get_ai_processing_stats()

    all_clusters = build_cluster_summaries()
    cluster_total = len(all_clusters)
    cluster_preview = sorted(all_clusters, key=lambda c: c['count'], reverse=True)[:AI_CLUSTER_PREVIEW]
    filter_key = request.GET.get('filter', 'all')

    documents_qs = (
        Document.objects.filter(is_archived=False)
        .select_related('uploaded_by', 'acc_area', 'program')
        .order_by('-uploaded_at')
    )
    documents_qs = filter_documents_queryset(documents_qs, filter_key)

    paginator = Paginator(documents_qs, AI_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    cluster_dist = (
        Document.objects.filter(is_archived=False)
        .exclude(cluster_label__isnull=True)
        .values('cluster_label')
        .annotate(count=Count('id'))
        .order_by('cluster_label')
    )
    labels_map = cluster_label_map()
    cluster_labels = []
    cluster_counts = []
    for row in cluster_dist:
        num = row['cluster_label']
        cluster_labels.append(labels_map.get(num) or f'Cluster {num}')
        cluster_counts.append(row['count'])

    doc_list = list(page_obj.object_list)
    for doc in doc_list:
        if doc.cluster_label is not None:
            doc.ai_cluster_display = labels_map.get(doc.cluster_label, f'Cluster {doc.cluster_label}')
        else:
            doc.ai_cluster_display = ''

    cluster_keywords = {}
    for cr in ClusterResult.objects.all():
        if cr.cluster_number not in cluster_keywords:
            cluster_keywords[cr.cluster_number] = cr.top_keywords[:6]

    # Saved with the latest run, so every Admin sees it whichever way it ran; the
    # session copy covers runs recorded before the chart was saved.
    from documents.ai_pipeline import last_elbow_summary
    elbow_data = last_elbow_summary() or request.session.get('elbow_data', None)
    recent_jobs = BackgroundJob.objects.order_by('-created_at')[:10]

    context = {
        'documents': doc_list,
        'page_obj': page_obj,
        'filter_key': filter_key,
        'filter_counts': {
            'all': stats['total_count'],
            'review': stats['dup_review_count'],
            'unclustered': stats['unclustered_count'],
            'pending': stats['pending_count'],
        },
        'processed_count': stats['processed_count'],
        'total_count': stats['total_count'],
        'unclustered_count': stats['unclustered_count'],
        'pending_count': stats['pending_count'],
        'cluster_labels': cluster_labels,
        'cluster_counts': cluster_counts,
        'cluster_keywords': cluster_keywords,
        # A summary, not a second copy of the Clusters page: this block used to
        # render every cluster while its own "Browse all" button linked to the same
        # list. Show the largest few and send the user to Clusters for the rest.
        'cluster_summaries': cluster_preview,
        'cluster_total': cluster_total,
        'cluster_label_map': labels_map,
        'dup_count': stats['dup_review_count'],
        'elbow_data': elbow_data,
        'recent_jobs': recent_jobs,
        # engine_info / pipeline_settings / last_pipeline_* fed the Clustering engine
        # card that this page no longer renders. engine_info is still built for the
        # per-document detail page, which shows the badge; the rest is not needed here.
    }
    return render(request, 'ai_processing/list.html', context)


@login_required
@admin_required
def ai_processing_detail(request, pk):
    """Show detailed AI results for a single document."""
    doc = get_object_or_404(
        Document.objects.select_related('uploaded_by', 'acc_area', 'program'),
        pk=pk,
    )
    cluster_results = doc.cluster_results.all()
    latest_cluster = cluster_results.first()
    cluster_peers = []
    if doc.cluster_label is not None:
        cluster_peers = (
            Document.objects.filter(is_archived=False, cluster_label=doc.cluster_label)
            .exclude(pk=doc.pk)
            .select_related('acc_area')[:8]
        )

    title = doc.title if len(doc.title) <= 40 else doc.title[:37] + '...'
    return render(request, 'ai_processing/detail.html', {
        'document': doc,
        'cluster_results': cluster_results,
        'latest_cluster': latest_cluster,
        'cluster_peers': cluster_peers,
        'engine_info': get_clustering_engine_info(request),
    })


@login_required
@admin_required
def run_ai_processing(request):
    """
    Run full AI pipeline on all documents (same logic as post-upload auto processing).
    """
    if request.method != 'POST':
        return redirect('ai_processing:list')

    total_docs = Document.objects.count()
    if total_docs < 2:
        messages.warning(request, 'At least 2 documents are required for AI processing.')
        return redirect('ai_processing:list')

    if bool(getattr(settings, 'AI_USE_BACKGROUND_JOBS', True)):
        job = enqueue_job('full_ai_pipeline', payload={}, created_by=request.user)
        ActivityLog.objects.create(
            user=request.user,
            action='ai_processing_queued',
            description=f'Queued AI processing job #{job.pk}',
        )
        if job.status == 'completed':
            messages.success(
                request,
                f'Reprocess complete. {total_docs} documents were updated (keywords, clusters, and duplicate checks).',
            )
        else:
            messages.info(
                request,
                f'Reprocess started for {total_docs} documents. Refresh this page in a moment to see updated results.',
            )
        return redirect('ai_processing:list')

    result_msg = run_full_ai_pipeline(request)

    if 'TF-IDF failed' in result_msg:
        messages.error(request, 'TF-IDF computation failed. Ensure documents have extracted text.')
        return redirect('ai_processing:list')

    if 'No documents' in result_msg:
        messages.warning(request, 'No documents in the repository.')
        return redirect('ai_processing:list')

    ActivityLog.objects.create(
        user=request.user,
        action='ai_processing',
        description=f'Ran AI processing: {result_msg}',
    )
    messages.success(request, result_msg)
    return redirect('ai_processing:list')


@login_required
@admin_required
def job_status(request, pk):
    job = get_object_or_404(BackgroundJob, pk=pk)
    return JsonResponse(
        {
            'id': job.pk,
            'job_type': job.job_type,
            'status': job.status,
            'result': job.result,
            'error': job.error,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        }
    )

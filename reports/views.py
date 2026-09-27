"""Views for generating reports (HTML view + CSV and styled Excel exports)."""
import csv

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.db.models import Count
from django.utils import timezone

from documents.models import Document
from documents.audit import log_activity
from documents.excel_export import csv_safe_row, openpyxl_available, single_sheet_workbook, excel_response
from accounts.decorators import admin_required

VALID_REPORT_TYPES = ('inventory', 'cluster', 'recent')


def _normalize_type(report_type):
    return report_type if report_type in VALID_REPORT_TYPES else 'inventory'


# The documents every report counts: the current ones. Archived versions are
# hidden everywhere else -- Dashboard, Repository, AI Processing -- and the
# reports used to include them, so their totals disagreed with the Dashboard's.
def _reported_documents():
    return Document.objects.filter(is_archived=False)


# The Recent report shows this many rows, and exports the same rows (it exported 200).
RECENT_REPORT_ROWS = 50


def _report_dataset(report_type):
    """Return (title, headers, rows) for the given report type.

    Shared by the CSV and Excel exporters so both stay in sync.
    """
    report_type = _normalize_type(report_type)

    if report_type == 'cluster':
        from ai_processing.dashboard_utils import cluster_label_map
        names = cluster_label_map()
        rows = [
            [f"Cluster {item['cluster_label']}", names.get(item['cluster_label'], ''), item['c']]
            for item in (
                _reported_documents().exclude(cluster_label__isnull=True)
                .values('cluster_label')
                .annotate(c=Count('id'))
                .order_by('cluster_label')
            )
        ]
        return 'Cluster Distribution Report', ['Cluster', 'Cluster Name', 'Document Count'], rows

    if report_type == 'recent':
        rows = [
            [
                doc.title,
                doc.year,
                doc.uploaded_at.strftime('%Y-%m-%d %H:%M'),
                doc.uploaded_by.username if doc.uploaded_by else 'N/A',
            ]
            for doc in _reported_documents().select_related('uploaded_by').order_by('-uploaded_at')[:RECENT_REPORT_ROWS]
        ]
        return 'Recent Upload Report', ['Title', 'Year', 'Uploaded At', 'Uploaded By'], rows

    # inventory (default)
    rows = []
    for doc in _reported_documents().select_related('uploaded_by', 'acc_area'):
        rows.append([
            doc.title,
            doc.file_type.upper(),
            doc.year,
            doc.document_type,
            doc.cluster_label if doc.cluster_label is not None else 'N/A',
            doc.acc_area.area_code if doc.acc_area else '',
            doc.uploaded_at.strftime('%Y-%m-%d'),
            doc.uploaded_by.username if doc.uploaded_by else 'N/A',
        ])
    headers = [
        'Title', 'File Type', 'Year', 'Document Type', 'Cluster',
        'Acc Area', 'Uploaded At', 'Uploaded By',
    ]
    return 'Document Inventory Report', headers, rows


@login_required
@admin_required
def reports_page(request):
    """Main reports page with report type selection."""
    from ai_processing.dashboard_utils import cluster_label_map

    report_type = _normalize_type(request.GET.get('type', 'inventory'))
    context = {'report_type': report_type, 'generated_at': timezone.localtime(timezone.now()),
               # Descriptive name of each cluster number, shown on hover wherever the number is.
               'cluster_names': cluster_label_map()}

    if report_type == 'inventory':
        context['documents'] = _reported_documents().select_related('uploaded_by', 'acc_area')
        context['title'] = 'Document Inventory Report'
        context['record_count'] = context['documents'].count()

    elif report_type == 'cluster':
        cluster_data = (
            _reported_documents().exclude(cluster_label__isnull=True)
            .values('cluster_label')
            .annotate(count=Count('id'))
            .order_by('cluster_label')
        )
        from documents.models import ClusterResult
        context['cluster_data'] = cluster_data
        context['cluster_keywords'] = ClusterResult.objects.all()
        context['title'] = 'Cluster Distribution Report'
        context['record_count'] = len(cluster_data)

    elif report_type == 'recent':
        recent = _reported_documents().select_related('uploaded_by').order_by('-uploaded_at')[:RECENT_REPORT_ROWS]
        context['documents'] = recent
        context['title'] = 'Recent Upload Report'
        context['record_count'] = len(recent)

    return render(request, 'reports/reports.html', context)


@login_required
@admin_required
def export_report_csv(request):
    """Export the selected report type as an organized CSV (title + metadata block)."""
    report_type = _normalize_type(request.GET.get('type', 'inventory'))
    log_activity(request, 'export_report', f'Exported CSV report: {report_type}.')

    title, headers, rows = _report_dataset(report_type)
    now = timezone.localtime(timezone.now())

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="{report_type}_report_{now:%Y%m%d_%H%M}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([title])
    writer.writerow([f'Generated: {now:%Y-%m-%d %H:%M}'])
    writer.writerow([f'Total records: {len(rows)}'])
    writer.writerow([])
    writer.writerow(headers)
    for row in rows:
        writer.writerow(csv_safe_row(row))
    return response


@login_required
@admin_required
def export_report_excel(request):
    """Export the selected report type as a styled Excel (.xlsx) workbook."""
    report_type = _normalize_type(request.GET.get('type', 'inventory'))

    if not openpyxl_available():
        # Excel engine unavailable — fall back to CSV so the download still works.
        return export_report_csv(request)

    log_activity(request, 'export_report', f'Exported Excel report: {report_type}.')

    title, headers, rows = _report_dataset(report_type)
    now = timezone.localtime(timezone.now())
    wb = single_sheet_workbook(title, headers, rows, generated_at=now)
    return excel_response(wb, f'{report_type}_report_{now:%Y%m%d_%H%M}')

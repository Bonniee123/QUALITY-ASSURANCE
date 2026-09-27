from django.contrib import admin
from .models import Document, ClusterResult, ActivityLog, BackgroundJob, ProcessingMetric

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'file_type', 'year', 'cluster_label', 'evidence_status', 'uploaded_at']
    list_filter = ['file_type', 'year', 'evidence_status', 'cluster_label']
    search_fields = ['title', 'description']

@admin.register(ClusterResult)
class ClusterResultAdmin(admin.ModelAdmin):
    list_display = ['document', 'cluster_number', 'cluster_label', 'created_at']
    list_filter = ['cluster_number']

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'description', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['description']


@admin.register(BackgroundJob)
class BackgroundJobAdmin(admin.ModelAdmin):
    list_display = ['job_type', 'status', 'created_by', 'created_at', 'finished_at']
    list_filter = ['job_type', 'status', 'created_at']
    search_fields = ['job_type', 'result', 'error']


@admin.register(ProcessingMetric)
class ProcessingMetricAdmin(admin.ModelAdmin):
    list_display = ['metric_name', 'metric_value', 'unit', 'created_at']
    list_filter = ['metric_name', 'created_at']

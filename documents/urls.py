"""URL patterns for documents app."""
from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('upload/', views.structured_upload, name='upload'),
    path('faculty-upload/', views.faculty_upload, name='faculty_upload'),
    path('bulk-upload/', views.bulk_upload, name='bulk_upload'),
    path('jobs/active/', views.jobs_active, name='jobs_active'),
    path('jobs/<int:pk>/status/', views.job_status, name='job_status'),
    path('upload-batches/', views.upload_batches, name='upload_batches'),
    path('bulk-delete/', views.documents_bulk_delete, name='bulk_delete'),
    path('repository/', views.repository_list, name='repository'),
    # A page per QA programme, so a category can be opened directly
    # instead of being filtered out of the whole repository.
    path('groups/', views.document_groups, name='groups'),
    path('groups/<str:code>/', views.document_group_detail, name='group_detail'),
    path('download/area-zip/', views.download_area_zip, name='download_area_zip'),
    path('area-submissions/', views.area_submissions, name='area_submissions'),
    path('clusters/', views.cluster_groups, name='clusters'),
    path('<int:pk>/', views.document_detail, name='detail'),
    path('<int:pk>/download/', views.document_download, name='download'),
    path('<int:pk>/view/', views.document_view, name='view'),
    path('<int:pk>/preview/', views.document_preview, name='preview'),
    path('<int:pk>/serve/', views.document_serve, name='serve'),
    path('<int:pk>/edit/', views.document_edit, name='edit'),
    path('<int:pk>/delete/', views.document_delete, name='delete'),
    path('<int:pk>/duplicate-confirm/', views.mark_duplicate_confirmed, name='duplicate_confirm'),
    path('<int:pk>/duplicate-dismiss/', views.dismiss_duplicate, name='duplicate_dismiss'),
    path('<int:pk>/retry-ocr/', views.retry_ocr, name='retry_ocr'),
    path('<int:pk>/mark-as-version/', views.mark_as_version, name='mark_as_version'),
    path('<int:pk>/unarchive/', views.unarchive_document, name='unarchive'),
]

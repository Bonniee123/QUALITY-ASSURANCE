"""
URL patterns for QA mapping.

Only the QA programme routes remain. The QA checklist -- requirement records,
their spreadsheet import and their attachments -- was removed as out of scope:
three records existed, all created on one day and never touched again. The
programmes stay because they are load-bearing elsewhere; ACCRED alone carries
95 of the archive's documents and drives the Program filter.
"""
from django.urls import path
from . import views

app_name = 'qa_mapping'

urlpatterns = [
    path('programs/', views.program_list, name='program_list'),
    path('programs/create/', views.program_create, name='program_create'),
    path('programs/<int:pk>/edit/', views.program_edit, name='program_edit'),
    path('programs/<int:pk>/delete/', views.program_delete, name='program_delete'),
]

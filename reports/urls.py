"""URL patterns for reports app."""
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_page, name='page'),
    path('export/', views.export_report_csv, name='export_csv'),
    path('export/excel/', views.export_report_excel, name='export_excel'),
]

"""URL patterns for AI processing app."""
from django.urls import path
from . import views

app_name = 'ai_processing'

urlpatterns = [
    path('', views.ai_processing_list, name='list'),
    path('<int:pk>/', views.ai_processing_detail, name='detail'),
    path('run/', views.run_ai_processing, name='run'),
    path('jobs/<int:pk>/status/', views.job_status, name='job_status'),
]

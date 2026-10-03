"""URL patterns for dashboard app."""
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('live/', views.live_status, name='live'),
]

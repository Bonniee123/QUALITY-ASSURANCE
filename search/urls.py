"""URL patterns for search app."""
from django.urls import path
from . import views

app_name = 'search'

urlpatterns = [
    path('', views.smart_search, name='search'),
]

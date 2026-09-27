from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('<int:pk>/open/', views.open_notification, name='open'),
    path('<int:pk>/read/', views.mark_read, name='mark_read'),
]

"""URL patterns for direct messaging."""
from django.urls import path

from . import views

app_name = 'messaging'

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('threads/', views.thread_list, name='thread_list'),
    path('threads/start/', views.thread_start, name='thread_start'),
    path('threads/<int:pk>/', views.thread_detail, name='thread_detail'),
    path('threads/<int:pk>/send/', views.message_send, name='message_send'),
    path('threads/<int:pk>/messages/<int:message_id>/delete/',
         views.message_delete, name='message_delete'),
    path('people/', views.people, name='people'),
    path('unread/', views.unread_count, name='unread_count'),
    # One request per tick: badge counts, thread list, and any new messages in
    # the conversation the reader has open.
    path('sync/', views.sync, name='sync'),
]

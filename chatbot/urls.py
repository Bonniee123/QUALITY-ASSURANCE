"""URL patterns for chatbot app."""
from django.urls import path
from . import views

app_name = 'chatbot'

urlpatterns = [
    path('', views.chatbot_page, name='page'),
    path('api/', views.chatbot_api, name='api'),
    # Conversation threads. The two routes above keep their names and behaviour,
    # so the floating widget and anything else already calling them still works.
    path('conversations/', views.conversation_list, name='conversation_list'),
    path('conversations/new/', views.conversation_create, name='conversation_create'),
    path('conversations/<int:pk>/', views.conversation_detail, name='conversation_detail'),
    path('conversations/<int:pk>/rename/', views.conversation_rename, name='conversation_rename'),
    path('conversations/<int:pk>/delete/', views.conversation_delete, name='conversation_delete'),
]

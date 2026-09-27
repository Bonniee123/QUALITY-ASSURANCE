from django.contrib import admin
from .models import ChatbotFAQ

@admin.register(ChatbotFAQ)
class ChatbotFAQAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'created_at']
    list_filter = ['category']
    search_fields = ['question', 'answer']

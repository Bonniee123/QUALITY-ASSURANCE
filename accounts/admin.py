from django.contrib import admin
from .models import UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'department', 'status']
    list_filter = ['role', 'status']
    search_fields = ['user__username', 'department']

from django.contrib import admin

from .models import QAProgram


@admin.register(QAProgram)
class QAProgramAdmin(admin.ModelAdmin):
    """
    Programmes are reference data the rest of the system leans on: a document
    carries one, and the Program filter on the dashboard and the repository is
    built from these rows.
    """
    list_display = ['code', 'name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['code']

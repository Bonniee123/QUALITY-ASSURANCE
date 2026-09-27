from django import forms
from django.contrib import admin

from .models import AccreditationArea


class AccreditationAreaForm(forms.ModelForm):
    class Meta:
        model = AccreditationArea
        fields = '__all__'

    def clean_area_code(self):
        """
        One area per code, whatever its capitals. The database's uniqueness is
        case-sensitive on SQLite, so "AREA I" could be added beside "Area I",
        and documents and Faculty assignments would split between the two.
        """
        code = ' '.join((self.cleaned_data.get('area_code') or '').split())
        clash = AccreditationArea.objects.filter(area_code__iexact=code)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f'Area "{clash.first().area_code}" already exists.')
        return code


@admin.register(AccreditationArea)
class AccreditationAreaAdmin(admin.ModelAdmin):
    """
    Areas are reference data: ten fixed AACCUP areas, seeded by migration.

    They had a dedicated maintenance page under "Accreditation Structure". That
    page went with the rest of the hierarchy; on the rare occasion an area name
    needs correcting, this admin is the place.
    """
    form = AccreditationAreaForm
    list_display = ('area_code', 'area_name', 'created_at')
    search_fields = ('area_code', 'area_name')
    ordering = ('area_code',)

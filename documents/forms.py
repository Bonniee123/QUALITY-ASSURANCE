"""
Forms for document upload and editing.
"""
import os
from django import forms
from django.conf import settings
from .models import Document
from .upload_validation import upload_content_problem

try:
    from qa_structure.models import AccreditationArea
except Exception:  # pragma: no cover
    AccreditationArea = None

# The year inputs carried min/max only in the HTML, so a request that skipped the
# browser stored 99999 or -1 as a document's year.
YEAR_MIN, YEAR_MAX = 2000, 2100


def clean_document_year(year):
    if year is not None and not (YEAR_MIN <= year <= YEAR_MAX):
        raise forms.ValidationError(f'Enter a year between {YEAR_MIN} and {YEAR_MAX}.')
    return year


DOCUMENT_TYPE_OPTIONS = [
    'Policy',
    'Report',
    'Manual',
    'Form',
    'Memorandum',
    'Minutes',
    'Resolution',
    'Plan',
    'Certificate',
    'Narrative',
    'Document',
]


def _choice_list(values):
    seen = set()
    out = [('', 'Select an option')]
    for raw in values:
        val = (raw or '').strip()
        if not val:
            continue
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((val, val))
    return out


class DocumentUploadForm(forms.ModelForm):
    """Form for uploading documents with metadata."""

    class Meta:
        model = Document
        fields = [
            'title', 'file', 'year', 'document_type',
            'qa_area', 'criterion', 'indicator', 'description',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter document title',
                'id': 'doc-title',
            }),
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'id': 'doc-file',
                'accept': '.pdf,.docx,.xlsx,.jpg,.jpeg,.png',
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 2024',
                'id': 'doc-year',
                'min': 2000,
                'max': 2100,
            }),
            'document_type': forms.TextInput(attrs={
                'class': 'form-select',
                'id': 'doc-type',
            }),
            'qa_area': forms.Select(attrs={
                'class': 'form-select',
                'id': 'doc-qa-area',
            }),
            'criterion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Criterion A',
                'id': 'doc-criterion',
            }),
            'indicator': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Indicator 1',
                'id': 'doc-indicator',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Brief description of the document',
                'id': 'doc-description',
                'rows': 3,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['document_type'].widget = forms.Select(attrs={'class': 'form-select', 'id': 'doc-type'})
        self.fields['document_type'].choices = _choice_list(DOCUMENT_TYPE_OPTIONS)

        qa_areas = []
        if AccreditationArea is not None:
            try:
                qa_areas = list(AccreditationArea.objects.values_list('area_code', flat=True).order_by('area_code'))
            except Exception:
                qa_areas = []
        if not qa_areas:
            qa_areas = [
                'Area I', 'Area II', 'Area III', 'Area IV', 'Area V',
                'Area VI', 'Area VII', 'Area VIII', 'Area IX', 'Area X',
            ]
        self.fields['qa_area'].choices = _choice_list(qa_areas)

    def clean_file(self):
        """Validate uploaded file extension and size."""
        file = self.cleaned_data.get('file')
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            allowed = getattr(settings, 'ALLOWED_UPLOAD_EXTENSIONS',
                              ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png'])
            if ext not in allowed:
                raise forms.ValidationError(
                    f'File type "{ext}" is not allowed. Accepted: {", ".join(allowed)}'
                )
            max_size = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 25 * 1024 * 1024)
            if file.size > max_size:
                raise forms.ValidationError(
                    f'File size exceeds the maximum limit of {max_size // (1024 * 1024)}MB.'
                )
            problem = upload_content_problem(file, ext)
            if problem:
                raise forms.ValidationError(f'This file cannot be uploaded: {problem}.')
        return file

    def clean_year(self):
        return clean_document_year(self.cleaned_data.get('year'))


class StructuredDocumentUploadForm(forms.ModelForm):
    """Single-file upload with QA metadata and the accreditation area."""

    class Meta:
        model = Document
        fields = [
            'title', 'file', 'year', 'document_type', 'description', 'program',
            'acc_area',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'id': 'struct-title'}),
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-control', 'id': 'struct-file',
                'accept': '.pdf,.docx,.xlsx,.jpg,.jpeg,.png',
            }),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100}),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'program': forms.Select(attrs={'class': 'form-select'}),
            'acc_area': forms.Select(attrs={'class': 'form-select', 'id': 'id_acc_area'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['program'].required = False
        self.fields['program'].queryset = self.fields['program'].queryset.filter(is_active=True)
        self.fields['program'].empty_label = '— No program —'
        self.fields['document_type'].choices = _choice_list(DOCUMENT_TYPE_OPTIONS)
        # Without an explicit empty_label these render Django's default "---------",
        # which told the user nothing about what the dropdown wanted.
        # Without an explicit empty_label this renders Django's default
        # "---------", which told the user nothing about what it wanted.
        self.fields['acc_area'].required = False
        self.fields['acc_area'].empty_label = '— Select area —'

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            allowed = getattr(settings, 'ALLOWED_UPLOAD_EXTENSIONS',
                              ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png'])
            if ext not in allowed:
                raise forms.ValidationError(
                    f'File type "{ext}" is not allowed. Accepted: {", ".join(allowed)}'
                )
            max_size = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 25 * 1024 * 1024)
            if file.size > max_size:
                raise forms.ValidationError(
                    f'File size exceeds the maximum limit of {max_size // (1024 * 1024)}MB.'
                )
            problem = upload_content_problem(file, ext)
            if problem:
                raise forms.ValidationError(f'This file cannot be uploaded: {problem}.')
        return file

    def clean_year(self):
        return clean_document_year(self.cleaned_data.get('year'))


class FacultyUploadForm(forms.ModelForm):
    """Simple single-file upload for Faculty, locked to their assigned area(s)."""

    class Meta:
        model = Document
        fields = [
            'title', 'file', 'year', 'document_type',
            'qa_area', 'program', 'description',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Enter document title', 'id': 'fac-title',
            }),
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-control', 'id': 'fac-file',
                'accept': '.pdf,.docx,.xlsx,.jpg,.jpeg,.png',
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g., 2024', 'id': 'fac-year',
                'min': 2000, 'max': 2100,
            }),
            'document_type': forms.Select(attrs={'class': 'form-select', 'id': 'fac-type'}),
            'qa_area': forms.Select(attrs={'class': 'form-select', 'id': 'fac-qa-area'}),
            'program': forms.Select(attrs={'class': 'form-select', 'id': 'fac-program'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'placeholder': 'Brief description of the document',
                'id': 'fac-description', 'rows': 3,
            }),
        }

    def __init__(self, *args, allowed_area_codes=None, **kwargs):
        super().__init__(*args, **kwargs)
        # NOTE: qa_area / document_type are model CharFields, so options must be set on
        # the *widget* (setting field.choices alone renders an empty <select>).
        self.fields['document_type'].widget.choices = _choice_list(DOCUMENT_TYPE_OPTIONS)
        self.fields['program'].required = False
        self.fields['program'].queryset = self.fields['program'].queryset.filter(is_active=True)
        self.fields['program'].empty_label = '— Select program —'

        codes = [c for c in (allowed_area_codes or []) if c]
        self._allowed_area_codes = set(codes)
        self.fields['qa_area'].required = True
        if len(codes) == 1:
            # Single assigned area: pre-select it (no blank "Select an option").
            self.fields['qa_area'].widget.choices = [(codes[0], codes[0])]
            if not self.is_bound:
                self.fields['qa_area'].initial = codes[0]
        else:
            self.fields['qa_area'].widget.choices = _choice_list(codes)

    def clean_qa_area(self):
        area = (self.cleaned_data.get('qa_area') or '').strip()
        if area not in self._allowed_area_codes:
            raise forms.ValidationError('You can only upload to your assigned accreditation area(s).')
        return area

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            allowed = getattr(settings, 'ALLOWED_UPLOAD_EXTENSIONS',
                              ['.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png'])
            if ext not in allowed:
                raise forms.ValidationError(
                    f'File type "{ext}" is not allowed. Accepted: {", ".join(allowed)}'
                )
            max_size = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 25 * 1024 * 1024)
            if file.size > max_size:
                raise forms.ValidationError(
                    f'File size exceeds the maximum limit of {max_size // (1024 * 1024)}MB.'
                )
            problem = upload_content_problem(file, ext)
            if problem:
                raise forms.ValidationError(f'This file cannot be uploaded: {problem}.')
        return file

    def clean_year(self):
        return clean_document_year(self.cleaned_data.get('year'))


class DocumentEditForm(forms.ModelForm):
    """Form for editing document metadata (no file re-upload)."""

    class Meta:
        model = Document
        fields = ['title', 'year', 'program', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100}),
            'program': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def clean_year(self):
        return clean_document_year(self.cleaned_data.get('year'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['program'].required = False
        self.fields['program'].queryset = self.fields['program'].queryset.filter(is_active=True)
        self.fields['program'].empty_label = '— No program —'

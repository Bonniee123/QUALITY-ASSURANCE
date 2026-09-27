"""Forms for QA requirements and evidence mapping."""
from django import forms
from .models import QAProgram


class QAProgramForm(forms.ModelForm):
    """Form for creating/editing a QA Program."""

    class Meta:
        model = QAProgram
        fields = ['name', 'code', 'description', 'color', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ISO-IQA'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'hsl(215, 65%, 50%) or #2563eb',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }



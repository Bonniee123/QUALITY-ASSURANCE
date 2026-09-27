# Document accreditation structure FKs

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('qa_structure', '0002_seed_areas_and_categories'),
        ('documents', '0004_document_program'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='acc_area',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents', to='qa_structure.accreditationarea'),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_parameter',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents', to='qa_structure.accreditationparameter'),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents', to='qa_structure.indicatorcategory'),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_indicator',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents', to='qa_structure.accreditationindicator'),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_required_evidence',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='linked_documents', to='qa_structure.requiredevidence'),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_evidence_label',
            field=models.CharField(blank=True, default='', help_text='Denormalized label from required evidence or manual entry.', max_length=512),
        ),
        migrations.AddField(
            model_name='document',
            name='acc_mapping_status',
            field=models.CharField(blank=True, choices=[('', 'Not set'), ('suggested', 'Suggested'), ('confirmed', 'Confirmed'), ('rejected', 'Rejected'), ('needs_review', 'Needs Review'), ('missing', 'Missing')], default='', help_text='Accreditation evidence mapping state (AI suggestions stay Suggested until confirmed).', max_length=20),
        ),
    ]

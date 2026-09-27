# Generated manually for QA accreditation structure

import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AccreditationArea',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('area_code', models.CharField(help_text='e.g. "Area I"', max_length=32, unique=True)),
                ('area_name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'verbose_name': 'Accreditation Area',
                'verbose_name_plural': 'Accreditation Areas',
                'ordering': ['area_code'],
            },
        ),
        migrations.CreateModel(
            name='AccreditationParameter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('parameter_code', models.CharField(help_text='e.g. "Parameter A"', max_length=64)),
                ('parameter_name', models.CharField(max_length=512)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('area', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='parameters', to='qa_structure.accreditationarea')),
            ],
            options={
                'verbose_name': 'Parameter',
                'verbose_name_plural': 'Parameters',
                'ordering': ['area', 'parameter_code'],
                'unique_together': {('area', 'parameter_code')},
            },
        ),
        migrations.CreateModel(
            name='IndicatorCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category_name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'Indicator Category',
                'verbose_name_plural': 'Indicator Categories',
                'ordering': ['category_name'],
            },
        ),
        migrations.CreateModel(
            name='AccreditationIndicator',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indicator_code', models.CharField(help_text='e.g. "S.1", "I.2", "O.1"', max_length=32)),
                ('indicator_statement', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('area', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='indicators', to='qa_structure.accreditationarea')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='indicators', to='qa_structure.indicatorcategory')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='indicators', to='qa_structure.accreditationparameter')),
            ],
            options={
                'verbose_name': 'Indicator',
                'verbose_name_plural': 'Indicators',
                'ordering': ['area', 'parameter', 'indicator_code'],
                'unique_together': {('parameter', 'indicator_code')},
            },
        ),
        migrations.CreateModel(
            name='RequiredEvidence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('evidence_label', models.CharField(max_length=512)),
                ('description', models.TextField(blank=True)),
                ('required_status', models.CharField(choices=[('required', 'Required'), ('recommended', 'Recommended'), ('optional', 'Optional')], default='required', max_length=20)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('indicator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='required_evidence_items', to='qa_structure.accreditationindicator')),
            ],
            options={
                'verbose_name': 'Required Evidence',
                'verbose_name_plural': 'Required Evidence',
                'ordering': ['indicator', 'evidence_label'],
            },
        ),
    ]

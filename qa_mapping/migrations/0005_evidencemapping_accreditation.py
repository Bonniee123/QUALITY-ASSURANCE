# EvidenceMapping: support accreditation RequiredEvidence; remarks; missing status

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('qa_structure', '0002_seed_areas_and_categories'),
        ('qa_mapping', '0004_seed_qa_programs'),
        ('documents', '0005_document_accreditation_structure'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='evidencemapping',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='evidencemapping',
            name='remarks',
            field=models.TextField(blank=True, default='', help_text='Staff notes when validating.'),
        ),
        migrations.AddField(
            model_name='evidencemapping',
            name='required_evidence',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='evidence_mappings', to='qa_structure.requiredevidence'),
        ),
        migrations.AlterField(
            model_name='evidencemapping',
            name='mapping_status',
            field=models.CharField(choices=[('suggested', 'Suggested'), ('confirmed', 'Confirmed'), ('needs_review', 'Needs Review'), ('rejected', 'Rejected'), ('missing', 'Missing')], default='suggested', max_length=20),
        ),
        migrations.AlterField(
            model_name='evidencemapping',
            name='reason',
            field=models.TextField(blank=True, default='', help_text='AI / system match explanation.'),
        ),
        migrations.AlterField(
            model_name='evidencemapping',
            name='requirement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='evidence_mappings', to='qa_mapping.qarequirement'),
        ),
        migrations.AddConstraint(
            model_name='evidencemapping',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(requirement__isnull=False, required_evidence__isnull=True)
                    | models.Q(requirement__isnull=True, required_evidence__isnull=False)
                ),
                name='evidence_mapping_single_target',
            ),
        ),
        migrations.AddConstraint(
            model_name='evidencemapping',
            constraint=models.UniqueConstraint(
                condition=models.Q(requirement__isnull=False),
                fields=('requirement', 'document'),
                name='uniq_evidencemapping_requirement_document',
            ),
        ),
        migrations.AddConstraint(
            model_name='evidencemapping',
            constraint=models.UniqueConstraint(
                condition=models.Q(required_evidence__isnull=False),
                fields=('required_evidence', 'document'),
                name='uniq_evidencemapping_requiredevidence_document',
            ),
        ),
    ]

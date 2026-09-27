"""Seed the six default QA programs the QA Office manages."""
from django.db import migrations


SEED_PROGRAMS = [
    {
        'code': 'ACCRED',
        'name': 'Accreditation',
        'description': 'General accreditation program managed by the QA Office.',
        'color': 'hsl(215, 65%, 50%)',
    },
    {
        'code': 'ISO-EXT',
        'name': 'ISO External Quality Audit',
        'description': 'ISO certification audits conducted by external bodies.',
        'color': 'hsl(0, 65%, 50%)',
    },
    {
        'code': 'ISO-INT',
        'name': 'ISO Internal Quality Audit',
        'description': 'Internal ISO audits conducted by the QA Office.',
        'color': 'hsl(25, 80%, 50%)',
    },
    {
        'code': 'BAICS',
        'name': 'Baseline Assessment Internal Control System',
        'description': 'BAICS — Baseline Assessment of Internal Control System.',
        'color': 'hsl(280, 50%, 50%)',
    },
    {
        'code': 'IA',
        'name': 'Institutional Accreditation',
        'description': 'Institutional Accreditation (IA) cycle.',
        'color': 'hsl(142, 55%, 42%)',
    },
    {
        'code': 'PQA',
        'name': 'Philippine Quality Award',
        'description': 'Philippine Quality Award (PQA) submissions.',
        'color': 'hsl(45, 95%, 45%)',
    },
]


def seed(apps, schema_editor):
    QAProgram = apps.get_model('qa_mapping', 'QAProgram')
    for entry in SEED_PROGRAMS:
        QAProgram.objects.get_or_create(
            code=entry['code'],
            defaults={
                'name': entry['name'],
                'description': entry['description'],
                'color': entry['color'],
                'is_active': True,
            },
        )


def unseed(apps, schema_editor):
    QAProgram = apps.get_model('qa_mapping', 'QAProgram')
    QAProgram.objects.filter(code__in=[p['code'] for p in SEED_PROGRAMS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('qa_mapping', '0003_qaprogram_qarequirement_program'),
    ]
    operations = [migrations.RunPython(seed, unseed)]

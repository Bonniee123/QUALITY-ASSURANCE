# Seed Areas I–X and default indicator categories

from django.db import migrations


AREA_DATA = [
    ('Area I', 'Vision, Mission, Goals and Objectives'),
    ('Area II', 'Faculty'),
    ('Area III', 'Curriculum and Instruction'),
    ('Area IV', 'Support to Students'),
    ('Area V', 'Research'),
    ('Area VI', 'Extension and Community Involvement'),
    ('Area VII', 'Library'),
    ('Area VIII', 'Physical Plant and Facilities'),
    ('Area IX', 'Laboratories'),
    ('Area X', 'Administration'),
]

CATEGORIES = [
    ('System – Inputs and Processes', 'Standard AACCUP-style system category.'),
    ('Implementation', 'Implementation phase indicators.'),
    ('Outcome/s', 'Outcome indicators.'),
]


def seed(apps, schema_editor):
    AccreditationArea = apps.get_model('qa_structure', 'AccreditationArea')
    IndicatorCategory = apps.get_model('qa_structure', 'IndicatorCategory')
    for code, name in AREA_DATA:
        AccreditationArea.objects.get_or_create(
            area_code=code,
            defaults={'area_name': name, 'description': ''},
        )
    for cat_name, desc in CATEGORIES:
        IndicatorCategory.objects.get_or_create(
            category_name=cat_name,
            defaults={'description': desc},
        )


def unseed(apps, schema_editor):
    AccreditationArea = apps.get_model('qa_structure', 'AccreditationArea')
    IndicatorCategory = apps.get_model('qa_structure', 'IndicatorCategory')
    AccreditationArea.objects.filter(area_code__in=[c for c, _ in AREA_DATA]).delete()
    IndicatorCategory.objects.filter(category_name__in=[c for c, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('qa_structure', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

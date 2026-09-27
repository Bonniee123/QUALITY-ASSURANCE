"""
Seed the department list from what accounts already record.

Before this, the dropdown was a constant holding "QA Office" alone. Any name a
profile already carries becomes a row here, so no existing account loses the
department shown against it, and the constant's own entry is created even when
nobody uses it yet.
"""
from django.db import migrations

FALLBACK = 'QA Office'


def seed_departments(apps, schema_editor):
    Department = apps.get_model('accounts', 'Department')
    UserProfile = apps.get_model('accounts', 'UserProfile')

    names = {
        (profile.department or '').strip()
        for profile in UserProfile.objects.all()
    }
    names.discard('')
    names.add(FALLBACK)

    for name in sorted(names):
        Department.objects.get_or_create(
            name=name,
            defaults={'is_active': True},
        )


def unseed_departments(apps, schema_editor):
    """
    Reversing drops only rows nobody is recorded against.

    A department someone belongs to is left alone: profiles store the name as
    text, so deleting the row would not corrupt them, but keeping it means a
    reverse followed by a re-apply does not silently change what the dropdown
    offers.
    """
    Department = apps.get_model('accounts', 'Department')
    UserProfile = apps.get_model('accounts', 'UserProfile')

    in_use = {
        (profile.department or '').strip()
        for profile in UserProfile.objects.all()
    }
    Department.objects.exclude(name__in=in_use).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_department'),
    ]

    operations = [
        migrations.RunPython(seed_departments, unseed_departments),
    ]

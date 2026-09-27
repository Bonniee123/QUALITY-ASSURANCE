"""
Back-fill UserProfile rows for any User created before signals existed
(e.g. superusers created via createsuperuser before the signal was wired).
Idempotent — safe to run on every deploy.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    for u in User.objects.all():
        if not UserProfile.objects.filter(user=u).exists():
            role = 'admin' if u.is_superuser else 'viewer'
            UserProfile.objects.create(user=u, role=role, status='active')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
    ]
    operations = [migrations.RunPython(backfill, noop)]

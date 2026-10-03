"""
Remove the conversations left behind by accounts deleted before the cleanup
existed (see messaging/signals.py): conversations with fewer than two people,
their messages, and the message notifications that pointed at them. These are
the "Deleted user" rows in Messages.
"""
from django.db import migrations
from django.db.models import Count


def remove_orphans(apps, schema_editor):
    Thread = apps.get_model('messaging', 'Thread')
    Notification = apps.get_model('notifications', 'Notification')
    orphans = list(Thread.objects.annotate(people=Count('participants', distinct=True))
                   .filter(people__lt=2).values_list('pk', flat=True))
    if not orphans:
        return
    Notification.objects.filter(category='message',
                                link__in=[f'/messages/?thread={pk}' for pk in orphans]).delete()
    Thread.objects.filter(pk__in=orphans).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0002_threadread_last_read_message_id'),
        ('notifications', '0003_notification_dedupe_key'),
    ]

    operations = [
        migrations.RunPython(remove_orphans, migrations.RunPython.noop),
    ]

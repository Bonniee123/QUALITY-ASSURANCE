"""
Drop chatbot FAQs describing the removed Missing Document Tracker.

The tracker app no longer exists (no models, no URLs, not in INSTALLED_APPS), but
two seeded FAQs still told users to open a "Missing Tracker" sidebar item and read
status badges on a page that is not there. Answering questions about a feature that
was removed is worse than not answering, so the rows go.

Documents are organized by accreditation Area instead — see chatbot/system_flows.py.
"""
from django.db import migrations, models


def delete_tracker_faqs(apps, schema_editor):
    ChatbotFAQ = apps.get_model('chatbot', 'ChatbotFAQ')
    ChatbotFAQ.objects.filter(category='tracker').delete()


def noop(apps, schema_editor):
    """The removed FAQs described a feature that no longer exists; nothing to restore."""


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(delete_tracker_faqs, noop),
        migrations.AlterField(
            model_name='chatbotfaq',
            name='category',
            field=models.CharField(
                choices=[
                    ('upload', 'Uploading'),
                    ('search', 'Searching'),
                    ('mapping', 'Evidence Mapping'),
                    ('areas', 'Area Submissions'),
                    ('ai', 'AI Processing'),
                    ('general', 'General'),
                ],
                default='general',
                max_length=20,
            ),
        ),
    ]

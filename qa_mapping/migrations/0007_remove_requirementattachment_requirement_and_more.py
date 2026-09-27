"""
Remove the QA checklist.

Three requirement records existed, all created on one day and never touched
again, with no attachments and no programme links. The page, its spreadsheet
import and its routes went with them. QAProgram stays: a document carries a
programme, and the Program filter on the dashboard and the repository is built
from those rows.

The first operation clears a table left behind by an app removed some time ago.
`tracker` has no directory, no models and is not in INSTALLED_APPS --
chatbot/migrations/0002_remove_tracker_faqs.py records its removal -- but its
table survived with three rows holding a foreign key into the requirements being
deleted here. Those rows already pointed at requirement ids that no longer
existed, so SQLite's integrity check refused the migration until the dead table
went. Dropping it here rather than by hand keeps the database reproducible from
the migrations alone.
"""
from django.db import migrations


def drop_orphaned_tracker_table(apps, schema_editor):
    """Remove the leftover tracker table and its migration records."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS tracker_missingdocument')
        cursor.execute("DELETE FROM django_migrations WHERE app = 'tracker'")


def noop(apps, schema_editor):
    """The table belonged to an app that no longer exists; nothing to restore."""


class Migration(migrations.Migration):

    dependencies = [
        ('qa_mapping', '0006_delete_evidencemapping'),
    ]

    operations = [
        migrations.RunPython(drop_orphaned_tracker_table, noop),
        migrations.RemoveField(
            model_name='requirementattachment',
            name='requirement',
        ),
        migrations.RemoveField(
            model_name='requirementattachment',
            name='uploaded_by',
        ),
        migrations.DeleteModel(
            name='QARequirement',
        ),
        migrations.DeleteModel(
            name='RequirementAttachment',
        ),
    ]

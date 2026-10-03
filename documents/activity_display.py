"""
What belongs on a dashboard, as opposed to what belongs in the audit trail.

Everything continues to be recorded. This module only decides what is *shown* on
the dashboard, and the rule is about the kind of event rather than about who is
looking:

  Archive events   -- something happened to the archive. Shared work, so anyone
                      who can see the documents may see that it happened.
  Personal events  -- logging in, viewing a page, searching, sending a message,
                      being denied access. These describe a person, not the
                      archive, and none of them appear on any dashboard. They stay
                      in the Audit Log, which is administrator-only and exists for
                      exactly this purpose.

Before this split the dashboard listed every row, so a QA Head saw the
administrator's logins, IP addresses and which settings pages they had opened.
"""
import re

# Actions that describe something happening to the archive.
ARCHIVE_ACTIONS = {
    'upload', 'bulk_upload', 'faculty_upload', 'upload_document',
    'edit_document', 'delete_document', 'bulk_delete_document', 'purge_document', 'upload_rejected',
    'archive_document', 'restore_document',
    'map_evidence', 'suggest_mappings', 'auto_map',
    'duplicate_confirmed', 'duplicate_dismissed',
    'ai_processing', 'ai_processing_queued', 'auto_ai_processing', 'retry_ocr',
    'export_report', 'export_report_zip',
    'create_requirement', 'edit_requirement', 'delete_requirement',
    'create_user', 'edit_user', 'delete_user',
}

# Actions that describe a person rather than the archive.
PERSONAL_ACTIONS = {
    'login', 'logout', 'login_failed', 'permission_denied',
    'view_document', 'view_settings', 'search',
    'send_message', 'delete_message',
}

_IP_SUFFIX = re.compile(r'\s*\(IP\s+[0-9a-fA-F:.]+\)\s*$')


def is_archive_action(action: str) -> bool:
    return action in ARCHIVE_ACTIONS


def clean_description(description: str) -> str:
    """
    Drop the trailing "(IP …)" for display.

    log_activity() appends the address to the description itself, so it renders
    anywhere the description does. That is right for the Audit Log and wrong for
    a dashboard tile, which is a summary for colleagues rather than a forensic
    record.
    """
    return _IP_SUFFIX.sub('', description or '').strip()


def dashboard_feed(queryset, viewer, limit: int = 15):
    """
    The dashboard's activity list.

    Archive events from anyone, plus the viewer's own personal events, with
    consecutive duplicates collapsed so "Viewed system settings page" cannot fill
    the panel four times over.
    """
    rows = []
    previous_key = None
    for entry in queryset.iterator():
        # Archive events only. Showing a person their own logins was the first
        # attempt, but "admin logged in - 0 minutes ago" on your own dashboard
        # tells you nothing you did not just do, and permission-denied notices
        # read as alarms. Every personal event stays in the Audit Log.
        if not is_archive_action(entry.action):
            continue

        entry.display_description = clean_description(entry.description)
        key = (entry.user_id, entry.action, entry.display_description)
        if key == previous_key:
            continue
        previous_key = key

        rows.append(entry)
        if len(rows) >= limit:
            break
    return rows

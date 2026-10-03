"""Central audit logging helpers for ActivityLog."""
from __future__ import annotations

from typing import Optional

from django.contrib.auth.models import AnonymousUser

# Human-readable labels for filter dropdown and table display.
ACTION_LABELS = {
    'login': 'Sign in',
    'logout': 'Sign out',
    'login_failed': 'Failed sign in',
    'permission_denied': 'Access denied',
    'create_user': 'User created',
    'edit_user': 'User updated',
    'delete_user': 'User deleted',
    'view_settings': 'Settings viewed',
    'view_document': 'Document viewed',
    'download': 'Document downloaded',
    'edit_document': 'Document metadata edited',
    'upload_document': 'Document uploaded',
    'delete_document': 'Document deleted',
    'bulk_delete_document': 'Document deleted (bulk)',
    'restore_document': 'Document restored (undo)',
    'purge_document': 'Document permanently deleted',
    'structured_upload': 'Structured upload',
    'bulk_upload': 'Bulk upload',
    'document_processed': 'Document processed',
    'upload_rejected': 'Upload turned away (duplicate)',
    'duplicate_confirmed': 'Duplicate confirmed',
    'duplicate_dismissed': 'Duplicate dismissed',
    'retry_ocr': 'OCR retry',
    'version_supersede': 'Version superseded',
    'version_unarchive': 'Version unarchived',
    'export_report': 'Report exported',
    'ai_processing': 'Document analysis run',
    'ai_processing_queued': 'Document analysis queued',
    'auto_ai_processing': 'Automatic document analysis',
    'create_program': 'QA program created',
    'create_requirement': 'QA requirement created',
    'import_requirements': 'Requirements imported',
    'search': 'Smart search',
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace('_', ' ').title())


def log_activity(request, action: str, description: str, user=None) -> None:
    """Persist an audit event; failures must not break the caller."""
    from .models import ActivityLog

    try:
        actor = user
        if actor is None and request is not None:
            candidate = getattr(request, 'user', None)
            if candidate and candidate.is_authenticated and not isinstance(candidate, AnonymousUser):
                actor = candidate

        if request is not None:
            from accounts.auth_security import get_client_ip

            ip = get_client_ip(request)
            if ip and ip != 'unknown' and f'IP {ip}' not in description:
                description = f'{description} (IP {ip})'

        ActivityLog.objects.create(
            user=actor,
            action=action[:50],
            description=description[:4000],
        )
    except Exception:
        pass


# The actions that make up a document's history, in the order they can happen.
DOCUMENT_EVENT_ACTIONS = (
    'upload_document', 'upload_rejected', 'document_processed', 'edit_document', 'delete_document', 'bulk_delete_document',
    'restore_document', 'purge_document', 'version_supersede', 'version_unarchive',
    'duplicate_confirmed', 'duplicate_dismissed',
)


def person_name(user) -> str:
    if user is None:
        return ''
    return ((user.get_full_name() or '').strip() or user.get_username())[:150]


def record_document_event(document, action: str, actor=None, *, request=None,
                          batch=None, description: str = ''):
    """
    Add one entry to a document's history.

    Unlike log_activity this does not swallow failures: an upload, deletion or
    restore that cannot be recorded should not be reported as done, so callers
    run it inside the same transaction as the change it records.
    """
    from .models import ActivityLog

    if actor is None and request is not None:
        candidate = getattr(request, 'user', None)
        if candidate is not None and candidate.is_authenticated:
            actor = candidate
    text = description or f'{action_label(action)}: {document.title}'
    if request is not None:
        from accounts.auth_security import get_client_ip
        ip = get_client_ip(request)
        if ip and ip != 'unknown':
            text = f'{text} (IP {ip})'
    return ActivityLog.objects.create(
        user=actor,
        actor_name=person_name(actor),
        action=action[:50],
        description=text[:4000],
        document=document,
        document_title=(document.title or '')[:255],
        batch=batch,
    )


def distinct_logged_actions():
    """Actions present in the database plus known labels (for filter UI)."""
    from .models import ActivityLog

    db_actions = set(ActivityLog.objects.values_list('action', flat=True).distinct())
    known = set(ACTION_LABELS.keys())
    return sorted(db_actions | known, key=lambda a: action_label(a).lower())

"""Template context for RBAC helpers."""
from django.conf import settings

from .permissions import (
    is_admin,
    is_faculty,
    is_qa_staff_or_admin,
    user_has_permission,
    PERM_VIEW_AI_PROCESSING,
    PERM_VIEW_REPORTS,
    PERM_DELETE_DOCUMENTS,
    PERM_RUN_AI_PROCESSING,
)


def rbac_context(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    return {
        'rbac_is_admin': is_admin(user),
        'rbac_is_faculty': is_faculty(user),
        'rbac_is_qa_staff_or_admin': is_qa_staff_or_admin(user),
        'rbac_can_view_ai_processing': user_has_permission(user, PERM_VIEW_AI_PROCESSING),
        'rbac_can_run_ai_processing': user_has_permission(user, PERM_RUN_AI_PROCESSING),
        'rbac_can_view_reports': user_has_permission(user, PERM_VIEW_REPORTS),
        'rbac_can_delete_documents': user_has_permission(user, PERM_DELETE_DOCUMENTS),
        # How long a bulk delete can be undone, for the undo toasts.
        'delete_undo_seconds': int(getattr(settings, 'DELETE_UNDO_SECONDS', 10)),
    }

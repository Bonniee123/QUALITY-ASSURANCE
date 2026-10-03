"""
Role-based access control (RBAC) for the QA Archiving System.

Roles:
  - admin: full system access (user management, delete, reports, manual AI runs, settings)
  - qa_staff (QA Head): daily document workflow (upload, search, repository, dashboard) across all areas
  - faculty: contributor scoped to assigned accreditation area(s); uploads, views, searches,
    and manages only their own area documents.

Administrator inherits all QA Head capabilities (see accounts.decorators.role_required).
"""
from __future__ import annotations

from typing import FrozenSet, List, Optional

ROLE_ADMIN = 'admin'
ROLE_QA_STAFF = 'qa_staff'
ROLE_FACULTY = 'faculty'
ROLES = (ROLE_ADMIN, ROLE_QA_STAFF, ROLE_FACULTY)

# --- Permission codenames (use in views, templates, and tests) ---

PERM_VIEW_DASHBOARD = 'view_dashboard'
PERM_UPLOAD_DOCUMENTS = 'upload_documents'
PERM_VIEW_REPOSITORY = 'view_repository'
PERM_VIEW_DOWNLOAD_DOCUMENTS = 'view_download_documents'
PERM_EDIT_DOCUMENT_METADATA = 'edit_document_metadata'
PERM_REVIEW_DUPLICATES = 'review_duplicates'
PERM_SEARCH_DOCUMENTS = 'search_documents'
PERM_VIEW_NOTIFICATIONS = 'view_notifications'
PERM_USE_CHATBOT = 'use_chatbot'
PERM_MANAGE_QA_MAPPING = 'manage_qa_mapping'
PERM_MANAGE_QA_STRUCTURE = 'manage_qa_structure'

PERM_DELETE_DOCUMENTS = 'delete_documents'
PERM_RUN_AI_PROCESSING = 'run_ai_processing'
PERM_VIEW_AI_PROCESSING = 'view_ai_processing'
PERM_VIEW_REPORTS = 'view_reports'
PERM_MANAGE_USERS = 'manage_users'
PERM_CONFIGURE_SETTINGS = 'configure_settings'

_QA_STAFF_PERMISSIONS: FrozenSet[str] = frozenset({
    PERM_VIEW_DASHBOARD,
    PERM_UPLOAD_DOCUMENTS,
    PERM_VIEW_REPOSITORY,
    PERM_VIEW_DOWNLOAD_DOCUMENTS,
    PERM_EDIT_DOCUMENT_METADATA,
    PERM_REVIEW_DUPLICATES,
    PERM_SEARCH_DOCUMENTS,
    PERM_VIEW_NOTIFICATIONS,
    PERM_USE_CHATBOT,
    PERM_MANAGE_QA_MAPPING,
    PERM_MANAGE_QA_STRUCTURE,
})

_ADMIN_PERMISSIONS: FrozenSet[str] = _QA_STAFF_PERMISSIONS | frozenset({
    PERM_DELETE_DOCUMENTS,
    PERM_RUN_AI_PROCESSING,
    PERM_VIEW_AI_PROCESSING,
    PERM_VIEW_REPORTS,
    PERM_MANAGE_USERS,
    PERM_CONFIGURE_SETTINGS,
})

# Faculty: scoped contributor. Can work with documents within their assigned area(s) only.
# Area-level scoping and "own uploads only" for edit/delete are enforced in the views.
# Notably excluded: QA mapping/structure, duplicate review, AI processing,
# reports, user management, and settings.
_FACULTY_PERMISSIONS: FrozenSet[str] = frozenset({
    PERM_VIEW_DASHBOARD,
    PERM_UPLOAD_DOCUMENTS,
    PERM_VIEW_REPOSITORY,
    PERM_VIEW_DOWNLOAD_DOCUMENTS,
    PERM_EDIT_DOCUMENT_METADATA,
    PERM_SEARCH_DOCUMENTS,
    PERM_VIEW_NOTIFICATIONS,
})

ROLE_PERMISSIONS = {
    ROLE_QA_STAFF: _QA_STAFF_PERMISSIONS,
    ROLE_ADMIN: _ADMIN_PERMISSIONS,
    ROLE_FACULTY: _FACULTY_PERMISSIONS,
}


def get_user_role(user) -> str | None:
    """Return profile role string, or None if unauthenticated / no profile."""
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_ADMIN
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    return profile.role


def is_active_user(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    if profile is None:
        return True
    return profile.status == 'active'


def user_has_permission(user, permission: str) -> bool:
    """True if user may perform the given action."""
    if not user or not user.is_authenticated:
        return False
    if not is_active_user(user):
        return False
    if user.is_superuser:
        return True
    role = get_user_role(user)
    if not role:
        return False
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def is_admin(user) -> bool:
    return user_has_permission(user, PERM_MANAGE_USERS)


def is_qa_staff_or_admin(user) -> bool:
    """True for Administrator or QA Head roles only (not Faculty)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return True
    role = get_user_role(user)
    return role in (ROLE_ADMIN, ROLE_QA_STAFF)


def is_faculty(user) -> bool:
    """True if the user's effective role is Faculty (superusers are never Faculty)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return False
    return get_user_role(user) == ROLE_FACULTY


def faculty_assigned_area_codes(user) -> List[str]:
    """Area codes assigned to a faculty user (empty list if none / not faculty)."""
    profile = getattr(user, 'profile', None)
    if profile is None:
        return []
    try:
        return list(profile.assigned_areas.values_list('area_code', flat=True))
    except Exception:
        return []


def faculty_area_scope(user) -> Optional[List[str]]:
    """
    Return the area-code scope for document querysets.

    - None  -> no scoping (Admin, QA Head, superuser): they see every area.
    - list  -> Faculty scope. May be empty when no area has been assigned yet,
               in which case the user should see no documents.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser:
        return None
    if get_user_role(user) != ROLE_FACULTY:
        return None
    return faculty_assigned_area_codes(user)


# Sentinel that cannot match any real AccreditationArea.area_code. Used so that a
# faculty member with no assigned areas matches zero documents (instead of all).
NO_AREA_SENTINEL = '\u0000__no_assigned_area__'


def scope_documents_for_user(qs, user):
    """Limit a Document queryset to a faculty member's assigned areas.

    Admin / QA Head / superuser querysets are returned unchanged. Faculty with no
    assigned area get an empty queryset.
    """
    scope = faculty_area_scope(user)
    if scope is None:
        return qs
    if not scope:
        return qs.none()
    from documents.area_utils import build_area_filter_q
    return qs.filter(build_area_filter_q(scope))


def user_can_access_document(user, doc, *, allow_deleted=False) -> bool:
    """
    True if the user may view a specific document (area scope for Faculty).

    A deleted document is no one's to open. Every view that serves a file asks
    this question, so answering it here is what keeps a saved link, an old
    notification or a typed address from downloading something after it was
    deleted. `allow_deleted` is for the undo, which has to judge a document
    that is deleted by definition.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not allow_deleted and (getattr(doc, 'deleted_at', None) or getattr(doc, 'purged_at', None)):
        return False
    if user.is_superuser:
        return True
    role = get_user_role(user)
    if role in (ROLE_ADMIN, ROLE_QA_STAFF):
        return True
    if role == ROLE_FACULTY:
        codes = set(faculty_assigned_area_codes(user))
        if not codes:
            return False
        from documents.area_utils import document_area_code
        return document_area_code(doc) in codes
    return False


def user_can_modify_document(user, doc, *, allow_deleted=False) -> bool:
    """True if the user may edit/delete a specific document.

    Admin (and superuser) may modify anything; QA Head may edit metadata; Faculty
    may only modify their own uploads that fall within their assigned area.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(doc, 'purged_at', None):
        return False
    if not allow_deleted and getattr(doc, 'deleted_at', None):
        return False
    if user.is_superuser:
        return True
    role = get_user_role(user)
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_QA_STAFF:
        return True
    if role == ROLE_FACULTY:
        return bool(doc.uploaded_by_id == user.id
                    and user_can_access_document(user, doc, allow_deleted=allow_deleted))
    return False

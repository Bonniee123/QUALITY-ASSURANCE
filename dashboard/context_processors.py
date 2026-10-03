"""
Context processor to provide sidebar badge counts and QA program quick-links on every page.
"""
from django.conf import settings

from accounts.permissions import scope_documents_for_user
from documents.models import Document


def sidebar_badges(request):
    """Add badge counts and QA program list for sidebar."""
    if not request.user.is_authenticated:
        return {}

    hide_advanced_qa_tools = bool(getattr(settings, 'HIDE_ADVANCED_QA_TOOLS', True))
    simple_ui_for_qa_head = bool(getattr(settings, 'SIMPLE_UI_FOR_QA_HEAD', True))
    simple_ui_mode = False
    try:
        profile = request.user.profile
        simple_ui_mode = (
            simple_ui_for_qa_head
            and not request.user.is_superuser
            and profile.role in ('qa_staff', 'faculty')
        )
    except Exception:
        simple_ui_mode = False

    try:
        # `live()` matters as much as the archived filter: a deleted document
        # is off every listing, so counting it made the badge disagree with
        # the page it links to -- 5 in the sidebar, 3 in the repository.
        base_qs = Document.objects.live().filter(is_archived=False)
        sidebar_doc_count = scope_documents_for_user(base_qs, request.user).count()
    except Exception:
        sidebar_doc_count = 0

    try:
        from qa_mapping.models import QAProgram
        sidebar_programs = list(QAProgram.objects.filter(is_active=True))
    except Exception:
        sidebar_programs = []

    return {
        'sidebar_doc_count': sidebar_doc_count,
        'sidebar_programs': sidebar_programs,
        'hide_advanced_qa_tools': hide_advanced_qa_tools,
        'simple_ui_mode': simple_ui_mode,
    }

"""
Live system awareness for the QA Archiving chatbot.

This module is what lets the assistant answer questions about the *actual*
state of the running system (how many documents exist, what is still
processing, duplicates to review, recent uploads, etc.) instead of only
reciting static help text.

Two surfaces:
  * get_system_stats(user)      -> permission-scoped numbers (dict)
  * live_context_text(user)     -> compact snapshot injected into the LLM prompt
  * match_live_data_query(...)  -> deterministic answers for "how many ..." style
                                   questions, so data questions work even when
                                   the local LLM is offline.

Everything is wrapped in defensive try/except: a reporting error must never
break the chatbot.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from accounts.permissions import (
    PERM_MANAGE_USERS,
    PERM_VIEW_REPOSITORY,
    is_faculty,
    user_has_permission,
)

logger = logging.getLogger(__name__)

# Documents flagged by AI as possible/confirmed duplicates.
_DUP_FLAGS = ("possible", "confirmed_dup")


def _user(request):
    return getattr(request, "user", None) if request is not None else None


def can_see_documents(user) -> bool:
    return bool(user) and user_has_permission(user, PERM_VIEW_REPOSITORY)


def get_system_stats(user) -> dict[str, Any]:
    """
    Return a permission-scoped snapshot of live system data.

    Keys are only populated when the user is allowed to see them; callers must
    treat any key as optional. Returns an empty dict if the user cannot even
    view the repository.
    """
    stats: dict[str, Any] = {}
    if not can_see_documents(user):
        return stats

    try:
        from accounts.permissions import faculty_area_scope, scope_documents_for_user
        from documents.models import Document

        # The same area scope as the Repository. These numbers and titles were
        # archive-wide, so a Faculty member assigned to one area was told the
        # totals, duplicate count and latest titles of every other area.
        active = scope_documents_for_user(Document.objects.filter(is_archived=False), user)
        scope = faculty_area_scope(user)
        if scope is not None:
            stats["scope_areas"] = list(scope)
        stats["total_documents"] = active.count()
        stats["my_documents"] = active.filter(uploaded_by=user).count()
        # Still ingesting: not processed, no recorded error, no text yet.
        stats["processing"] = active.filter(
            is_processed=False, processing_error="", extracted_text="", ocr_text=""
        ).count()
        # Duplicate review and clustering are QA work. Only Admin and QA Head
        # can confirm or dismiss a duplicate, and the Clusters page is closed to
        # Faculty, so the Repository, the group pages and the Dashboard all stop
        # showing them those figures. The assistant was still reading both out,
        # and pointing Faculty at a duplicates filter and a KPI card that are no
        # longer on their screen.
        if not is_faculty(user):
            stats["duplicates"] = active.filter(duplicate_status__in=_DUP_FLAGS).count()
            cluster_ids = (
                active.exclude(cluster_label__isnull=True)
                .values_list("cluster_label", flat=True)
                .distinct()
            )
            stats["clusters"] = len(set(cluster_ids))
        stats["recent"] = [
            {
                "title": d.title,
                "uploaded_at": d.uploaded_at,
                "by": (d.uploaded_by.get_username() if d.uploaded_by else "unknown"),
            }
            for d in active.select_related("uploaded_by").order_by("-uploaded_at")[:5]
        ]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("chatbot stats: document metrics failed: %s", exc)

    # Account totals — admin only.
    if user_has_permission(user, PERM_MANAGE_USERS):
        try:
            from django.contrib.auth.models import User as AuthUser

            stats["total_users"] = AuthUser.objects.filter(is_active=True).count()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("chatbot stats: user metrics failed: %s", exc)

    return stats


def _fmt_recent(recent: list[dict[str, Any]]) -> str:
    if not recent:
        return "none yet"
    parts = []
    for item in recent:
        ts = item.get("uploaded_at")
        when = ts.strftime("%Y-%m-%d") if ts else ""
        parts.append(f"{item['title']} ({when})".strip())
    return "; ".join(parts)


def live_context_text(user) -> str:
    """Compact, model-friendly snapshot of live system state for the LLM prompt."""
    stats = get_system_stats(user)
    if not stats:
        return "No live data available for this user."

    lines = []
    if "total_documents" in stats:
        where = ""
        if "scope_areas" in stats:
            areas = ", ".join(stats["scope_areas"])
            where = f" in your area(s) {areas}" if areas else " in your areas (none assigned yet)"
        lines.append(
            f"Documents archived (active){where}: {stats['total_documents']} "
            f"(uploaded by this user: {stats.get('my_documents', 0)})."
        )
    if stats.get("processing"):
        lines.append(f"Documents still being processed: {stats['processing']}.")
    if "duplicates" in stats:
        lines.append(f"Possible duplicates to review: {stats['duplicates']}.")
    if stats.get("clusters"):
        lines.append(f"Document clusters detected: {stats['clusters']}.")
    if "total_users" in stats:
        lines.append(f"Active user accounts: {stats['total_users']}.")
    if stats.get("recent"):
        lines.append("Most recent uploads: " + _fmt_recent(stats["recent"]) + ".")
    return "\n".join(lines) if lines else "No live data available for this user."


# --- Deterministic "how many / what is the status" answers --------------------

# Intent: the user is asking about live numbers/state, not how to use a feature.
_QUANT_INTENT = re.compile(
    r"\b(how many|how much|number of|count of|total (number|count|documents|files)|"
    r"do i have|are there|is there any|what(?:'s| is) the (status|count|number)|"
    r"how complete|how far along|progress|status of)\b"
)


def _wants_quant(message_lower: str) -> bool:
    return bool(_QUANT_INTENT.search(message_lower))


# Intent: the user wants to see recent/latest items (no "how many" needed).
_RECENT_INTENT = re.compile(r"\b(recent|latest|newest|recently)\b")


def _wants_recent(message_lower: str) -> bool:
    return bool(
        _RECENT_INTENT.search(message_lower)
        and re.search(r"\b(document|documents|file|files|upload|uploads|uploaded)\b", message_lower)
    )


def match_live_data_query(message_lower: str, request) -> Optional[dict[str, Any]]:
    """
    Answer quantitative/state questions directly from the database.

    Returns a chatbot response dict, or None if this is not a live-data
    question (so the caller can fall through to other tiers).
    """
    user = _user(request)
    if not _wants_quant(message_lower) and not _wants_recent(message_lower):
        return None
    if not can_see_documents(user):
        return None

    stats = get_system_stats(user)
    if not stats:
        return None

    def resp(answer: str, confidence: float = 0.9) -> dict[str, Any]:
        return {"answer": answer, "category": "live_data", "confidence": confidence}

    # Duplicates
    if "duplicate" in message_lower:
        if "duplicates" not in stats:
            return resp(
                "Duplicate review is handled by the QA Head and the Administrator. "
                "Your uploads are still checked automatically: an exact copy is refused "
                "at upload, so anything filed in your area has already passed that check."
            )
        n = stats.get("duplicates", 0)
        if n:
            return resp(
                f"There {'is' if n == 1 else 'are'} {n} possible duplicate "
                f"{'document' if n == 1 else 'documents'} to review. Open the Dashboard "
                "duplicates KPI or the Repository duplicates filter to confirm or dismiss them."
            )
        return resp("No possible duplicates are currently flagged for review.")

    # Still processing
    if re.search(r"\b(processing|pending|still working|in progress|finished processing)\b", message_lower):
        n = stats.get("processing", 0)
        if n:
            return resp(
                f"{n} document{'s are' if n != 1 else ' is'} still being processed. "
                "AI extraction and clustering run in the background — check AI Processing for status."
            )
        return resp("All uploaded documents have finished processing.")

    # Users (admin)
    if re.search(r"\b(user|account|staff|people)\b", message_lower):
        if "total_users" in stats:
            return resp(f"There are {stats['total_users']} active user accounts in the system.")
        return resp("Only administrators can view account totals.")

    # Clusters.
    # "clusters" did not match \bcluster\b, so the plural -- the way anyone
    # actually asks -- fell past this branch to the generic snapshot.
    if re.search(r"\b(clusters?|groupings?|groups?)\b", message_lower):
        if "clusters" not in stats:
            return resp(
                "Document clusters are a QA Head and Administrator view. "
                "Use Repository to find files in your assigned area(s)."
            )
        n = stats.get("clusters", 0)
        return resp(f"The system has grouped documents into {n} cluster{'s' if n != 1 else ''}.")

    # Recent uploads
    if re.search(r"\b(recent|latest|last|newest)\b", message_lower):
        recent = stats.get("recent") or []
        if not recent:
            return resp("No documents have been uploaded yet.")
        listed = _fmt_recent(recent)
        return resp(f"Most recent uploads: {listed}.")

    # My documents
    if re.search(r"\bmy\b", message_lower) and re.search(r"\b(document|file|upload)\b", message_lower):
        return resp(
            f"You have uploaded {stats.get('my_documents', 0)} document(s). "
            f"There are {stats.get('total_documents', 0)} active document(s) "
            + ("in your assigned area(s)." if "scope_areas" in stats else "in the archive.")
        )

    # Generic documents/files total
    if re.search(r"\b(document|file|archive)\b", message_lower):
        total = stats.get("total_documents", 0)
        mine = stats.get("my_documents", 0)
        return resp(
            f"There are {total} active document(s) "
            + ("in your assigned area(s) " if "scope_areas" in stats else "in the archive ")
            + f"({mine} uploaded by you)."
        )

    # Quantitative intent but no specific subject. Only answer with an overall
    # snapshot when the question is actually about this system — otherwise let
    # the off-topic guard handle it.
    from .scope import is_system_related

    if is_system_related(message_lower):
        return resp(live_context_text(user), confidence=0.7)
    return None

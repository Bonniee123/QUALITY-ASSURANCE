"""
Structured navigation knowledge for the QA Archiving chatbot.
"""
from __future__ import annotations

import re
from typing import Any, Optional
# Pages a Faculty member cannot open. Every one of these topics walked them
# through a screen that is not in their sidebar and that the server refuses:
# Reports, AI Processing, User Management and Settings are admin only, Area
# Submissions and Clusters are QA Head and Admin. The answers said so in
# passing ("admin only"), but still gave the steps.
_STAFF_ONLY_TOPICS = frozenset({
    'area_submissions', 'clusters', 'reports', 'ai_processing', 'users', 'settings',
})


def navigation_topics(request) -> list[dict[str, Any]]:
    """
    Scorable topics: keywords (lowercase) + step-by-step answer.

    A Faculty member is given only the topics about pages they have. Passing
    ``None`` returns everything, which is what the keyword scorer in scope.py
    wants: it is deciding whether a message is about this system at all, not
    what to answer with.
    """
    topics = _all_topics()
    user = getattr(request, 'user', None) if request is not None else None
    if user is not None:
        from accounts.permissions import is_faculty
        if is_faculty(user):
            return [t for t in topics if t['id'] not in _STAFF_ONLY_TOPICS]
    return topics


def _all_topics() -> list[dict[str, Any]]:
    # The specific topics come first: on a tie the earlier topic wins, and
    # "download all documents of Area II" scores the same on "download" and
    # "documents" (Repository) as on "download all" and "all documents of area".
    return [
        {
            "id": "password",
            "keywords": {
                "password", "passwords", "forgot my password", "reset password", "change password", "locked out",
            },
            "answer": (
                "Passwords are managed by an Administrator — there is no self-service password page.\n"
                "1) Ask an Administrator to reset it.\n"
                "2) Administrator: open User Management, click Edit (pencil) on the account, type a new "
                "password, and Save. Give the new password to the user directly.\n"
                "If sign-in says the account is deactivated, the Administrator can switch it back on in the "
                "Access column of User Management."
            ),
        },
        {
            "id": "visibility",
            "keywords": {
                "who can see", "who sees", "can see my", "see my upload", "see my document",
                "visible", "visibility", "who has access",
            },
            "answer": (
                "Who can see a document depends on its accreditation area:\n"
                "- Administrators and QA Heads can see every document in every area.\n"
                "- Faculty can see only the documents in the area(s) assigned to them — including other "
                "Faculty members' uploads in those same areas.\n"
                "- Faculty can edit or delete only their own uploads; Administrators and QA Heads can edit or "
                "delete any document.\n"
                "Area assignments are set by an Administrator in User Management."
            ),
        },
        {
            "id": "duplicate_review",
            "keywords": {
                "duplicate", "duplicates", "needs review", "mark as clear", "as clear",
                "confirm duplicate", "not a duplicate", "exact copy", "same file",
            },
            "answer": (
                "Every upload is checked for duplicates:\n"
                "- An exact copy of a file already in the archive is refused at upload.\n"
                "- A file whose wording or image is very similar to another is kept and marked Needs review.\n"
                "- Clear means no duplicate was found, or a reviewer decided it is not one. Confirmed duplicate "
                "means a reviewer decided it is one.\n"
                "To review (QA Head or Administrator):\n"
                "1) Open Repository and set the Duplicate filter to Needs review.\n"
                "2) Open the document's Details — Similar Documents shows what it matches and how closely.\n"
                "3) Click Mark as clear to keep both, or Confirm duplicate.\n"
                "Faculty uploads are reviewed by the QA Head."
            ),
        },
        {
            "id": "area_zip",
            "keywords": {
                "zip", "download all", "download area", "area zip", "all documents of area",
                "all files of area", "whole area", "entire area",
            },
            "answer": (
                "To download a whole area at once:\n"
                "1) Open Repository.\n"
                "2) Choose the area in the Area filter.\n"
                "3) Click Download area as ZIP at the top — every file in that area comes in one ZIP.\n"
                "With no area chosen, the same button reads Download all areas as ZIP and gives every area "
                "you can access, one folder per area. Faculty get only their assigned area(s)."
            ),
        },
        {
            "id": "dashboard",
            "keywords": {
                "dashboard",
                "home",
                "summary",
                "analytics",
                "kpi",
                "chart",
                "export",
                "csv",
                "statistics",
            },
            "answer": (
                "The Dashboard shows total documents, duplicates to review, upload trend chart, "
                "upload activity calendar, and file format breakdown. Filter by QA program and period; "
                "Export Excel downloads a styled summary. Go to Dashboard in the left sidebar."
            ),
        },
        {
            # "document", "file" and "add" were keywords here, so any question
            # containing "document" -- "how do I delete a document?", "documents
            # about zebra crossings" -- was answered with these upload steps.
            "id": "upload",
            "keywords": {
                "upload",
                "bulk",
                "pdf",
                "docx",
                "import",
                "submit",
                "attach",
            },
            "answer": (
                "1) Open Upload Document in the left sidebar — one page takes a single file or many at once "
                "(drag and drop).\n"
                "2) Optionally choose a QA program. Faculty also choose which of their assigned accreditation "
                "areas the files belong to.\n"
                "3) Click Upload. Files are saved straight away; the title, year and type are read from each "
                "file, and text extraction, duplicate checks and clustering run in the background — you get a "
                "notification when they finish. Correct a title or year afterwards with Edit in the Repository.\n"
                "Exact copies and near-identical files are refused at upload; similar ones are saved and flagged "
                "as Needs review for the QA Head.\n"
                "Supported formats: PDF, DOCX, XLSX, JPG, PNG."
            ),
        },
        {
            "id": "delete",
            "keywords": {"delete", "deleting", "remove", "trash"},
            "answer": (
                "1) Open Repository in the left sidebar.\n"
                "2) Open the Actions menu at the end of the document's row, choose Delete and confirm.\n"
                "Administrators and QA Heads can delete any document, and can tick several rows to delete them "
                "together. Faculty can delete only their own uploads in their assigned area(s).\n"
                "If you delete the newer version of a document, its older version comes back to the Repository."
            ),
        },
        {
            "id": "checklist",
            "keywords": {"checklist", "qa checklist", "requirement", "requirements"},
            "answer": (
                "There is no QA Checklist page in this system. To see which faculty have submitted documents "
                "for each accreditation area, open Area Submissions (QA Head/Admin) in the left sidebar; to find "
                "documents, use the Repository."
            ),
        },
        {
            "id": "repository",
            "keywords": {
                "repository",
                "archive",
                "list",
                "documents",
                "folder",
                "version",
                "archived",
                "download",
                "edit",
                "preview",
                "duplicate",
                "format",
                "filter",
            },
            "answer": (
                "1) Open Document Repository in the left sidebar.\n"
                "2) Filter by Program, Area, Year, File format, Cluster, or Duplicate status, or use the Smart Search box.\n"
                "3) Use View to preview, Details for metadata and similar files, Edit for title/year/program/description, or Download.\n"
                "QA Head/Admin: filter Duplicate by Needs review, open Details, compare similar files, then Mark as clear or Confirm duplicate.\n"
                "QA Head/Admin: use Download all areas as ZIP (leave Area filter on All Areas) for one ZIP with a folder per area, "
                "or pick a specific Area and use Download area as ZIP for that area only.\n"
                "Faculty downloads are limited to their assigned area(s)."
            ),
        },
        {
            "id": "area_submissions",
            "keywords": {
                "area submissions",
                "submissions",
                "submission",
                "consolidate",
                "consolidation",
                "per area",
                "by area",
                "zip",
                "who submitted",
                "monitor",
                "gather",
                "combine",
            },
            "answer": (
                "Area Submissions (QA Head/Admin) is in the left sidebar, under Repository.\n"
                "1) Each accreditation area shows assigned-faculty count, files submitted, submission progress, "
                "and last upload.\n"
                "2) Click an area to see each assigned faculty member, who has or has NOT submitted, and the exact "
                "files they uploaded.\n"
                "3) Click \"Download area as ZIP\" to consolidate the whole area into one download.\n"
                "You can also consolidate from the Repository by choosing an Area and clicking Download area as ZIP.\n"
                "Faculty do not have Area Submissions — they use Repository to view files in their assigned area."
            ),
        },
        {
            # Both of these are in the sidebar for every role and neither had a
            # topic, so "what is Document Groups" and "how do I message the QA
            # Head" fell through to the generic overview.
            "id": "document_groups",
            "keywords": {
                "group",
                "groups",
                "document group",
                "document groups",
                "programme",
                "no category",
                "uncategorised",
                "uncategorized",
            },
            "answer": (
                "Document Groups (left sidebar) gives each QA program a page of its own: one card per "
                "program with how many files it holds, plus a No category card for documents not filed "
                "under any program.\n"
                "Open a card to list that program's documents, with the same Actions menu as the "
                "Repository - View file, Details, Download, and Edit or Delete where you are allowed "
                "them. Search within this group opens the Repository filtered to that program.\n"
                "The counts follow your own scope: a Faculty member sees their assigned area(s) only."
            ),
        },
        {
            "id": "messages",
            "keywords": {
                "message",
                "messages",
                "inbox",
                "chat",
                "conversation",
                "thread",
                "reply",
                "contact",
                "send a message",
            },
            "answer": (
                "Messages (left sidebar) is direct messaging between accounts. Anyone may message "
                "anyone: a QA Head can reach a named Faculty member and the other way round.\n"
                "1) Open Messages and start a conversation. Search people by name, or by accreditation "
                "area to list that area's members.\n"
                "2) Type your message. You can attach a document from the archive - the reference is "
                "checked against whoever reads it, so nobody sees a file outside their own access.\n"
                "Unread conversations show a count on the Messages item in the sidebar."
            ),
        },
        {
            "id": "roles",
            "keywords": {
                "role",
                "roles",
                "faculty",
                "qa head",
                "qa staff",
                "permission",
                "permissions",
                "access",
                "scope",
                "assigned area",
            },
            "answer": (
                "There are three roles:\n"
                "- Administrator: full access (User Management, Settings, Audit Log, AI Processing, Reports).\n"
                "- QA Head: the daily workflow across ALL accreditation areas (dashboard, upload, repository, "
                "search, area submissions, clusters, consolidation), including deleting documents.\n"
                "- Faculty: a contributor limited to assigned accreditation area(s) — upload, repository, "
                "and search only within their area; edit/delete only their own uploads.\n"
                "Admins set each user's role and a faculty member's area(s) under User Management."
            ),
        },
        {
            "id": "clusters",
            "keywords": {
                "cluster",
                "clusters",
                "group",
                "similar",
                "k-means",
                "kmeans",
            },
            "answer": (
                "Clusters (QA Head/Admin) is in the left sidebar under Main, below Area Submissions.\n"
                "1) Each card is an AI document group (Cluster 0, 1, 2, …) with a document count.\n"
                "2) Click a cluster to see every document in that group.\n"
                "3) You can also filter by cluster in the Repository.\n"
                "How clusters are formed: documents are grouped within each accreditation area and document "
                "type; in each group the number of clusters is chosen by the silhouette score (the Elbow method "
                "is the fallback), and near-identical clusters are merged. An Admin can re-run it from AI Processing.\n"
                "Faculty do not have a Clusters page — they use Repository to view files in their assigned area."
            ),
        },
        {
            "id": "search",
            "keywords": {"search", "find", "lookup", "smart", "keyword", "tf-idf", "facet"},
            "answer": (
                "1) Open Repository in the left sidebar.\n"
                "2) Type in the Smart Search box at the top of the page — it matches titles, extracted/OCR text, metadata, facets, and QA program.\n"
                "3) Narrow further with the Program, Area, Year, File format, Cluster and Duplicate filters.\n"
                "4) Open a result to preview or view details."
            ),
        },
        {
            "id": "programs",
            "keywords": {
                "program",
                "programs",
                "accreditation",
                "iso",
                "baics",
                "pqa",
                "ia",
                "qa program",
            },
            "answer": (
                "A QA program is an accreditation stream (ISO, BAICS, IA, PQA, "
                "and so on).\n"
                "1) Choose one when you upload a document, to file it under that "
                "stream.\n"
                "2) Use the Program filter on the Repository or the Dashboard to "
                "see only that stream's documents."
            ),
        },
        {
            "id": "qa_structure",
            "keywords": {
                "qa structure",
                "accreditation structure",
                "area i",
                "parameter",
                "indicator",
                "aaccup",
                "ched",
            },
            "answer": (
                "Documents are organized by accreditation area (Area I–X). Faculty are assigned their area(s) "
                "in User Management, and the Repository and Area Submissions filter by area.\n"
                "Parameters, indicators and required-evidence lines are not tracked in this system; the list of "
                "areas itself is maintained by an Administrator in the Django admin (Accreditation Areas)."
            ),
        },
        {
            "id": "reports",
            "keywords": {"report", "reports", "export", "inventory", "excel"},
            "answer": (
                "1) Open Reports in the left sidebar (admin only).\n"
                "2) Choose a report type: document inventory, cluster distribution, or recent uploads.\n"
                "3) Download as CSV or Excel.\n"
                "To gather every file in one accreditation area, use Download area as ZIP from the Repository or "
                "Area Submissions instead."
            ),
        },
        {
            "id": "ai_processing",
            "keywords": {
                "ai",
                "processing",
                "pipeline",
                "cluster",
                "k-means",
                "elbow",
                "ocr",
                "duplicate",
            },
            "answer": (
                "1) Open AI Processing in the left sidebar.\n"
                "2) Check status of runs on your documents (TF-IDF, clustering, duplicate checks).\n"
                "3) When processing completes, open a document to see its keywords, cluster, and duplicate results."
            ),
        },
        {
            "id": "notifications",
            "keywords": {"notification", "notifications", "bell", "alert", "unread"},
            "answer": (
                "1) Click the bell icon in the top bar.\n"
                "2) Open an alert to go to its linked page.\n"
                "3) Use Mark all read to clear unread badges without leaving your current page."
            ),
        },
        {
            "id": "users",
            "keywords": {"user", "users", "account", "accounts", "create user", "manage user"},
            "answer": (
                "1) Open User Management in the left sidebar (admin only).\n"
                "2) Create accounts and assign a role (Administrator, QA Head, or Faculty).\n"
                "3) For Faculty, also assign one or more accreditation area(s) that scope what they can see.\n"
                "4) Save — users can sign in with their new credentials."
            ),
        },
        {
            "id": "settings",
            "keywords": {"setting", "settings", "configuration", "system"},
            "answer": (
                "1) Open Settings in the left sidebar (admin only).\n"
                "2) It shows the supported file formats, the upload size limit, and each AI engine's status and "
                "last run.\n"
                "Settings is read-only: these values are set in the server configuration."
            ),
        },
        {
            "id": "chatbot",
            "keywords": {"chatbot", "chat", "assistant", "help", "guide"},
            "answer": (
                "You are already in AI Chatbot Guidance. Ask about any sidebar item by name "
                "(e.g. upload, repository, search, reports) for step-by-step help."
            ),
        },
    ]


def score_navigation_match(message_lower: str, topic: dict[str, Any]) -> int:
    # A keyword counts from the start of a word: "document" still finds
    # "documents", but "list" no longer matched inside "checklist", nor "ai"
    # inside "email" or "detail".
    score = 0
    for kw in topic["keywords"]:
        if re.search(rf"\b{re.escape(kw)}", message_lower):
            score += 2
    return score


def match_navigation_topic(message_lower: str, request) -> Optional[tuple[str, str]]:
    """
    If the user is clearly asking where something is or how to open a module,
    return (answer_plain, category). Answers include a single primary URL.
    """
    topics = navigation_topics(request)
    best: Optional[tuple[int, dict[str, Any]]] = None
    for t in topics:
        s = score_navigation_match(message_lower, t)
        if best is None or s > best[0]:
            best = (s, t)
    if not best or best[0] < 2:
        return None
    t = best[1]
    text = t["answer"].replace("**", "")
    return text, "system_navigation"


def general_system_overview(request) -> str:
    """Step-by-step guide for broad help questions (no URLs)."""
    from .system_flows import general_system_guide
    return general_system_guide()


def is_broad_help_query(message_lower: str) -> bool:
    if len(message_lower) < 2:
        return False
    patterns = [
        r"\bhelp\b",
        r"\bhow do i use\b",
        r"\bhow to use\b",
        r"\bwhat can (you|this|the system)\b",
        r"\bguide me\b",
        r"\bwhere (do|should) i (start|go)\b",
        r"\boverview\b",
        r"\bwalk ?through\b",
        r"\bnavigate\b",
        r"\bwhole system\b",
        r"\bentire system\b",
    ]
    return any(re.search(p, message_lower) for p in patterns)


def build_ollama_navigation_context(request) -> str:
    """Workflows + page links for the LLM prompt."""
    from .system_flows import build_full_system_context
    return build_full_system_context(request)

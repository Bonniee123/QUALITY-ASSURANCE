"""
Smart Hybrid Chatbot Engine — answers only from QA Archiving System knowledge.

Tiers (high to low priority):
  0) Broad help / overview
  1) Navigation topics (where is X)
  2) Accreditation FAQ + regex SYSTEM_KNOWLEDGE
  3) Off-topic guard (refuse unrelated questions)
  4) Local Ollama with strict system-only prompt (optional)
  5) Admin ChatbotFAQ matches
  6) Fallback with site map
"""
import logging
import re
from typing import Any, Optional

import requests
from django.conf import settings
from django.db.models import Q

from .models import ChatbotFAQ
from .scope import (
    build_ollama_system_prompt,
    is_off_topic,
    is_system_related,
    out_of_scope_response,
    wants_document_context,
)
from .system_navigation import (
    build_ollama_navigation_context,
    general_system_overview,
    is_broad_help_query,
    match_navigation_topic,
)
from .system_status import (
    can_see_documents,
    live_context_text,
    match_live_data_query,
)
from documents.models import Document

logger = logging.getLogger(__name__)

# Conversation memory (session-backed)
_HISTORY_KEY = "qa_chat_history"
_HISTORY_MAX_TURNS = 6

OLLAMA_MODEL_NAME = getattr(settings, "OLLAMA_MODEL", "qwen2.5:0.5b")
OLLAMA_API_URL = getattr(settings, "OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
CHATBOT_OLLAMA_ENABLED = getattr(settings, "CHATBOT_OLLAMA_ENABLED", True)

# The hosted-model settings are read when a question is asked rather than when
# this module is imported, so the provider can be changed, or a key supplied,
# without editing code, and so a test can override them.
DEFAULT_LLM_PROVIDER = "ollama"

SYSTEM_KNOWLEDGE = {
    r"\b(upload|add).*(document|file)\b": (
        "Use Upload Document in the sidebar: one page takes a single file or many at once (drag and drop). "
        "Supported formats: PDF, DOCX, XLSX, JPG, PNG. Title, year and type are read from each file, and text "
        "extraction, duplicate checks and clustering run in the background after upload."
    ),
    r"\b(bulk).*(upload|file)\b": (
        "Upload Document in the sidebar takes many files at once — drag and drop them onto the page."
    ),
    r"\b(search|find).*(document|file)\b": (
        "Use the Smart Search box at the top of the Document Repository. It matches titles, extracted/OCR text, "
        "metadata, keywords, clusters, and accreditation area/program."
    ),
    r"\b(can'?t|cannot|unable to|where).*(find|locate|see)\b": (
        "Open Document Repository and use the Smart Search box plus the Program, Area, Year, File format, and "
        "Cluster filters. If you are Faculty, you only see documents in your assigned area(s). Tell me the page "
        "or feature you are looking for (e.g. upload, area submissions, reports) and I'll point you to it."
    ),
    r"\b(faculty|role|roles|permission|access|scope)\b": (
        "There are three roles: Administrator (full access), QA Head (full workflow across all areas), and "
        "Faculty (limited to assigned accreditation area(s) — they upload/view/search/edit/download only their "
        "area, and edit/delete only their own uploads). Admins set roles and faculty areas in User Management."
    ),
    r"\b(consolidat|combine|gather|merge).*(file|document|area|submission)\b": (
        "To consolidate an area: in the Document Repository pick an Area and click \"Download area as ZIP\", or "
        "open Area Submissions, select the area, and download it as a ZIP. Area Submissions also shows which "
        "faculty have or have not submitted."
    ),
    r"\b(area submission|submissions|who submitted|per area)\b": (
        "Area Submissions (QA Head/Admin, in the sidebar under Repository) shows every accreditation area with "
        "assigned-faculty count, files submitted, submission progress, and last upload. Open an area to see each "
        "faculty member, who has or hasn't submitted, and their files, and to download the area as a ZIP."
    ),
    r"\b(zip|download all|download everything)\b": (
        "Choose an Area in the Document Repository (or open Area Submissions and select the area) and click "
        "\"Download area as ZIP\" to download every file in that area in one archive."
    ),
    r"\b(edit).*(document|metadata|title)\b": (
        "In the Repository, open the Actions menu at the end of the row and choose Edit, "
        "or open Details and use Edit there. "
        "A modal lets you change title, year, QA program, and description."
    ),
    r"\b(view|preview|open).*(document|file|docx|pdf)\b": (
        "In the Repository, open the Actions menu at the end of the row and choose View file. "
        "DOCX files preview with logos when LibreOffice is installed."
    ),
    r"\b(cluster|grouping|k-means|k means)\b": (
        "K-Means groups similar documents within each accreditation area and document type. In each group "
        "the number of clusters is chosen by the silhouette score, with the Elbow method as the fallback. "
        "The Clusters page, the Repository cluster column and the Dashboard cluster card are QA Head and "
        "Administrator views; Reports also breaks documents down by cluster."
    ),
    r"\b(tf-?idf|keyword)\b": (
        "TF-IDF highlights important terms per document for similarity search and clustering."
    ),
    r"\b(evidence|map|mapping|organize|organized)\b": (
        "Documents are organized by accreditation Area and QA Program (there is no separate evidence-mapping "
        "page). Use the Repository filters and Smart Search to find documents by area, year, type, or keyword, "
        "and Area Submissions to see what each area's faculty have submitted."
    ),
    r"\b(ocr|scanned|scan)\b": (
        "OCR reads text from clear scans or images so those files become searchable."
    ),
    r"\b(delete|remove).*(document|file)\b": (
        "In the Repository, open the Actions menu at the end of the row, choose Delete and confirm. "
        "Administrators and QA Heads can delete any document; Faculty can delete only their own "
        "uploads in their area."
    ),
    r"\b(dashboard|calendar|overview)\b": (
        "The Dashboard shows total documents, duplicates to review, upload trend, upload activity calendar, "
        "and file format breakdown. Filter by program and period; Export Excel downloads a styled summary."
    ),
    r"\b(duplicate)\b": (
        "AI flags possible duplicate uploads. Confirming or dismissing one is QA Head and Administrator "
        "work: they see the count on the Dashboard, the Duplicate column and filter in the Repository, "
        "and the Confirm or Mark as clear buttons in document details. An exact copy is refused at "
        "upload, so nothing identical reaches the archive."
    ),
    r"\b(report|inventory)\b": (
        "Reports (admin) includes document inventory, cluster distribution, and recent uploads, exportable as "
        "CSV/Excel. To gather all files in one area, use Download area as ZIP from the Repository or Area Submissions."
    ),
    r"\b(notification|bell|alert)\b": (
        "Notifications appear under the bell in the top bar. Click an item to open its page; "
        "Mark all read clears badges without leaving your current page."
    ),
    r"\b(user|admin|account)\b": (
        "Administrators manage accounts under User Management — assign a role (Administrator, QA Head, Faculty) "
        "and, for Faculty, their accreditation area(s). Settings holds system configuration; Audit Log records activity."
    ),
    r"\b(program|accreditation|iso|baics|pqa)\b": (
        "QA Programs group documents by accreditation stream (ISO, BAICS, PQA, etc.). "
        "An uploaded document can carry one, and the Program filter uses it."
    ),
    r"\b(version|archive|supersede)\b": (
        "When a newer version replaces a document, the older one is archived and hidden from the Repository, "
        "and a v2/v3 badge marks the newer document. Linking versions is not available from the document "
        "details in this version of the system."
    ),
    r"\b(file format|pdf|docx|png)\b.*\b(filter|repository)\b": (
        "In the Repository, use the File format dropdown to filter by PDF, DOCX, PNG, and other extensions."
    ),
}


def match_accreditation_faq(message_lower: str, request) -> Optional[dict]:
    """
    Definitions for the QA structure this system actually stores.

    Four entries were removed: a block explaining "Parameter A", and the
    questions "what is a parameter", "what is an indicator" and "what is
    required evidence". None of the three has a model, a table or a page here --
    `qa_structure` holds `AccreditationArea` and nothing else, and `qa_mapping`
    holds `QAProgram` and nothing else. The assistant was defining a hierarchy
    the archive does not record, while its own navigation answer said plainly
    that "Parameters, indicators and required-evidence lines are not tracked in
    this system". Two answers, one system, and only one of them true.
    """
    topics = [
        ("what is an area", "An Accreditation Area (e.g. Area I-X) is how this system groups documents. "
                            "A Faculty member is assigned one or more areas and sees those."),
        ("what is a qa program", "A QA Program (ACCRED, ISO-INT, ISO-EXT, BAICS, IA, PQA) is the accreditation "
                                 "stream a document belongs to. Tag one at upload, or filter by it in the Repository."),
        ("how do i upload a document", (
            "1) Open Upload Document in the left sidebar - it takes one file or many at once.\n"
            "2) Optionally choose a QA program; Faculty also choose their accreditation area.\n"
            "3) Click Upload. Title, year and type are read from each file; correct them later with Edit."
        )),
    ]
    for needle, text in topics:
        if needle in message_lower:
            return {"answer": text, "category": "accreditation", "confidence": 0.93}
    return None


def _fetch_document_context(message_lower: str, request=None) -> str:
    if not wants_document_context(message_lower):
        return ""
    # Only surface archived file content to users allowed to view the repository.
    user = getattr(request, "user", None) if request is not None else None
    if not can_see_documents(user):
        return ""
    user_words = set(re.findall(r"\w+", message_lower))
    stopwords = {
        "how", "do", "i", "a", "the", "what", "is", "to", "can", "you", "me",
        "tell", "about", "where", "why", "who", "when", "document", "file",
    }
    meaningful = [w for w in user_words - stopwords if len(w) > 3][:3]
    if not meaningful:
        return ""
    query = Q()
    for word in meaningful:
        query |= Q(title__icontains=word) | Q(extracted_text__icontains=word)
    # Exclude superseded/archived versions so previews match the live repository,
    # and only documents this user may open: the snippets go into the model's
    # prompt, so an unscoped query could put another area's text in an answer.
    from accounts.permissions import scope_documents_for_user
    docs = scope_documents_for_user(
        Document.objects.filter(query, is_archived=False), user,
    ).distinct()[:3]
    if not docs:
        return ""
    blocks = []
    for doc in docs:
        snippet = (doc.extracted_text or "")[:800]
        blocks.append(f"--- {doc.title} ---\n{snippet or 'No extracted text.'}")
    return "\n".join(blocks)


def _load_history(request) -> list[dict[str, str]]:
    """Return prior conversation turns from the session (oldest first)."""
    if request is None or not hasattr(request, "session"):
        return []
    history = request.session.get(_HISTORY_KEY, [])
    return history if isinstance(history, list) else []


def _save_turn(request, user_message: str, answer: str) -> None:
    """Append a turn to session history, capped at the most recent N turns."""
    if request is None or not hasattr(request, "session"):
        return
    history = _load_history(request)
    history.append({"user": user_message[:500], "bot": (answer or "")[:500]})
    request.session[_HISTORY_KEY] = history[-_HISTORY_MAX_TURNS:]
    request.session.modified = True


def _format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-_HISTORY_MAX_TURNS:]:
        user_text = (turn.get("user") or "").strip()
        bot_text = (turn.get("bot") or "").strip()
        if user_text:
            lines.append(f"User: {user_text}")
        if bot_text:
            lines.append(f"Assistant: {bot_text}")
    return "\n".join(lines)


def _scoped_prompt(user_message: str, request) -> str:
    """
    The prompt that keeps a model answering about this system only.

    Both the local and the hosted model are given exactly this text. Sharing it
    matters: the scope guard, the navigation map and the live archive figures
    are what stop the model inventing features, so a second provider must not
    quietly get a weaker prompt than the first.
    """
    nav_block = build_ollama_navigation_context(request)
    doc_context = _fetch_document_context(user_message.lower(), request)
    user = getattr(request, "user", None) if request is not None else None
    live_context = live_context_text(user)
    history = _format_history(_load_history(request))
    return build_ollama_system_prompt(
        nav_block, doc_context, user_message, live_context=live_context, history=history
    )


def _ollama_answer(user_message: str, request) -> Optional[dict[str, Any]]:
    if not CHATBOT_OLLAMA_ENABLED:
        return None
    prompt = _scoped_prompt(user_message, request)
    payload = {"model": OLLAMA_MODEL_NAME, "prompt": prompt, "stream": False}
    response = requests.post(
        OLLAMA_API_URL, json=payload,
        timeout=getattr(settings, "CHATBOT_LLM_TIMEOUT", 25),
    )
    if response.status_code != 200:
        logger.error("Ollama API Error: %s", response.text)
        return None
    text = response.json().get("response", "").strip()
    if not text:
        return None
    return {"answer": text, "category": "ai_generated", "confidence": 0.88}


def _gemini_answer(user_message: str, request) -> Optional[dict[str, Any]]:
    """
    Ask Google's hosted model, using the same system-only prompt as the local one.

    Returns None rather than raising for every failure -- no key, wrong model
    name, quota exhausted, a reply that was blocked -- because the caller treats
    None as "this tier had nothing" and carries on to the FAQ and site-map
    tiers. The chatbot must never go blank because a paid service is unhappy.
    The reason is logged so a failure can be diagnosed instead of guessed at.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("Gemini is selected but GEMINI_API_KEY is empty.")
        return None

    model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    base = getattr(
        settings, "GEMINI_API_BASE",
        "https://generativelanguage.googleapis.com/v1beta/models",
    )
    prompt = _scoped_prompt(user_message, request)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,      # keep it factual about the archive
            "maxOutputTokens": 512,  # a chat answer, not an essay; also caps cost
        },
    }
    response = requests.post(
        f"{base}/{model}:generateContent",
        json=payload,
        headers={"x-goog-api-key": api_key},
        timeout=getattr(settings, "CHATBOT_LLM_TIMEOUT", 25),
    )
    if response.status_code != 200:
        # The body names the cause, most often an unknown model or a spent quota.
        logger.error("Gemini API error %s: %s", response.status_code, response.text[:400])
        return None

    try:
        candidates = response.json().get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError, ValueError) as error:
        logger.error("Gemini returned no usable answer (%s): %s",
                     type(error).__name__, response.text[:300])
        return None

    if not text:
        return None
    return {"answer": text, "category": "ai_generated", "confidence": 0.88}


def _model_answer(user_message: str, request) -> Optional[dict[str, Any]]:
    """
    Run whichever model is configured, and keep the local one as a safety net.

    Only this function knows which provider is in use; every tier above it is
    unchanged. With the default setting it calls Ollama exactly as before.
    """
    provider = getattr(settings, "CHATBOT_LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
    if provider == "none":
        return None

    if provider == "gemini":
        answer = _gemini_answer(user_message, request)
        if answer:
            return answer
        if getattr(settings, "GEMINI_FALLBACK_TO_OLLAMA", True):
            logger.info("Gemini gave no answer; trying the local model.")
            return _ollama_answer(user_message, request)
        return None

    return _ollama_answer(user_message, request)


def _compute_response(user_message: str, request=None) -> dict[str, Any]:
    if not user_message or not user_message.strip():
        return {
            "answer": "Please type a question about this QA Archiving System and I will guide you.",
            "category": "general",
            "confidence": 0,
        }

    message_lower = user_message.lower().strip()

    # Tier 0: live system data ("how many documents", "what's missing", etc.)
    try:
        live = match_live_data_query(message_lower, request)
        if live:
            return live
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("chatbot live-data tier failed: %s", exc)

    acc = match_accreditation_faq(message_lower, request)
    if acc:
        return acc

    if is_broad_help_query(message_lower):
        return {
            "answer": general_system_overview(request),
            "category": "system_overview",
            "confidence": 0.95,
        }

    nav = match_navigation_topic(message_lower, request)
    if nav:
        answer, cat = nav
        return {"answer": answer, "category": cat, "confidence": 0.92}

    for pattern, response in SYSTEM_KNOWLEDGE.items():
        if re.search(pattern, message_lower):
            return {
                "answer": response,
                "category": "system_guide",
                "confidence": 0.85,
            }

    if is_off_topic(message_lower):
        return out_of_scope_response(request)

    # Unrelated chit-chat (e.g. "hello", "thanks") — refuse immediately; do not wait on Ollama.
    if not is_system_related(message_lower):
        return out_of_scope_response(request)

    try:
        ai = _model_answer(user_message, request)
        if ai:
            return ai
    except requests.exceptions.ConnectionError:
        logger.error("Could not reach the language model.")
    except requests.exceptions.ReadTimeout:
        return {
            "answer": (
                "The AI model took too long. Try a shorter question, or ask where to find a page "
                "(Dashboard, Upload, Repository, Search, Reports)."
            ),
            "category": "general",
            "confidence": 0.5,
        }
    except Exception as e:
        logger.error("Ollama integration error: %s", e)

    faqs = ChatbotFAQ.objects.all()
    user_words = set(re.findall(r"\w+", message_lower))
    stopwords = {
        "how", "do", "i", "a", "the", "what", "is", "to", "can", "you", "me",
        "tell", "about", "where", "why",
    }
    meaningful_words = user_words - stopwords

    best_match = None
    best_score = 0
    for faq in faqs:
        score = 0
        faq_keywords = set(k.lower() for k in faq.keywords) if faq.keywords else set()
        question_words = set(re.findall(r"\w+", faq.question.lower())) - stopwords
        score += len(meaningful_words & faq_keywords) * 3
        score += len(meaningful_words & question_words) * 2
        if score > best_score:
            best_score = score
            best_match = faq

    if best_match and best_score >= 2:
        return {
            "answer": best_match.answer,
            "category": best_match.get_category_display(),
            "confidence": min(best_score / 10.0, 0.8),
        }

    tail = ""
    if request is not None:
        try:
            tail = (
                "\n\nTry: \"How do I upload documents?\", \"How do I find a document?\", "
                "or \"What does the dashboard show?\"."
            )
        except Exception:
            pass

    return {
        "answer": (
            "I could not match that to a feature in this system."
            + tail
        ),
        "category": "general",
        "confidence": 0.3,
    }


def get_chatbot_response(user_message: str, request=None) -> dict[str, Any]:
    """
    Public entry point: compute a response and record conversation memory.

    The QA Archive Agent is consulted first. It answers questions *about the
    archive* -- finding documents, outstanding evidence, summaries, why something
    was classified as it was -- from the database, and returns None for anything
    else. Everything it declines falls through to the original navigation, FAQ and
    scope engine below, so none of that behaviour was replaced.
    """
    if request is not None and user_message and user_message.strip():
        try:
            from .agent import answer as agent_answer

            agent_result = agent_answer(user_message, request)
            if agent_result is not None:
                try:
                    _save_turn(request, user_message.strip(), agent_result.get('answer', ''))
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("chatbot memory save failed: %s", exc)
                return agent_result
        except Exception as exc:  # pragma: no cover - never break the chatbot
            logger.warning("QA agent failed, falling back to rules: %s", exc)

    result = _compute_response(user_message, request)
    try:
        if user_message and user_message.strip():
            _save_turn(request, user_message.strip(), result.get("answer", ""))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("chatbot memory save failed: %s", exc)
    return result

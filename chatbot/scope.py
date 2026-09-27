"""
Scope control: keep chatbot answers inside QA Archiving System knowledge.
"""
from __future__ import annotations

import re

# Terms that indicate the user is asking about this application.
_SYSTEM_VOCAB = {
    'upload', 'document', 'documents', 'file', 'files', 'repository', 'archive',
    'search', 'dashboard', 'report', 'reports', 'evidence', 'mapping', 'map',
    'checklist', 'requirement', 'program', 'accreditation',
    'iso', 'baics', 'pqa', 'area', 'areas', 'parameter', 'indicator', 'ocr', 'cluster',
    'duplicate', 'ai', 'processing', 'notification', 'bell', 'admin', 'role', 'roles',
    'user', 'settings', 'chatbot', 'help', 'navigate', 'sidebar', 'preview',
    'download', 'edit', 'bulk', 'qa', 'capstone', 'archiving', 'system',
    'pdf', 'docx', 'xlsx', 'png', 'format', 'calendar', 'export', 'csv', 'excel',
    'faculty', 'consolidate', 'consolidation', 'submission', 'submissions',
    'zip', 'permission', 'permissions', 'access', 'scope', 'assigned', 'login',
    'logout', 'audit', 'staff', 'head',
}

# Clear off-topic intents — only trigger when the message is NOT system-related.
_OFF_TOPIC_PATTERNS = [
    r'\b(weather|forecast|temperature)\b',
    r'\b(recipe|cook|ingredient)\b',
    r'\b(tell me a )?(joke|poem|story|rap)\b',
    r'\b(capital of|population of|president of)\b',
    r'\b(bitcoin|crypto|stock market|forex)\b',
    r'\b(homework|essay|thesis|assignment)\b(?!.*\b(document|evidence|qa)\b)',
    r'\b(write (code|a program|python|javascript|java))\b(?!.*\b(system|upload|report)\b)',
    r'\b(who won|world cup|nba|nfl|celebrity)\b',
    r'\btranslate .+ to (spanish|french|tagalog|english)\b',
]

# Only pull uploaded document text when the user is clearly asking about archive content.
_DOCUMENT_CONTEXT_PATTERNS = [
    r'\b(document|file|upload|archive).*(title|content|text|say|about|mention)\b',
    r'\bwhat (does|did|is in)\b.*\b(document|file|report|policy|manual)\b',
    r'\b(find|search|look).*(in my|in the|uploaded|repository)\b',
    r'\bwhich document\b',
    r'\bmy (uploaded|archived) (file|document)\b',
]


def _message_words(message_lower: str) -> set[str]:
    return set(re.findall(r'[a-z0-9]+', message_lower))


def system_topic_score(message_lower: str) -> int:
    from .system_navigation import navigation_topics

    words = _message_words(message_lower)
    score = len(words & _SYSTEM_VOCAB)
    for topic in navigation_topics(None):
        for kw in topic.get('keywords', ()):
            if kw in message_lower:
                score += 2
    return score


def is_system_related(message_lower: str) -> bool:
    return system_topic_score(message_lower) >= 1


def is_off_topic(message_lower: str) -> bool:
    if is_system_related(message_lower):
        return False
    for pattern in _OFF_TOPIC_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    # Generic knowledge question with zero system vocabulary.
    if re.match(r'^(what|who|when|where|why|how|explain|define)\b', message_lower):
        return True
    return False


def wants_document_context(message_lower: str) -> bool:
    return any(re.search(p, message_lower) for p in _DOCUMENT_CONTEXT_PATTERNS)


def out_of_scope_response(request=None) -> dict:
    tail = ''
    if request is not None:
        try:
            tail = (
                '\n\nYou can ask things like:\n'
                '- "Where do I upload documents?"\n'
                '- "How do I download an area as a ZIP?"\n'
                '- "What is Area Submissions?"\n'
                '- "Help me navigate"\n'
            )
        except Exception:
            pass
    return {
        'answer': (
            'I only answer questions about this QA Archiving System — uploads, repository, '
            'search, area submissions and consolidation, reports, AI processing, roles, and navigation.'
            + tail
        ),
        'category': 'out_of_scope',
        'confidence': 0.95,
    }


def build_ollama_system_prompt(
    nav_block: str,
    document_context: str,
    user_message: str,
    live_context: str = "",
    history: str = "",
) -> str:
    doc_section = document_context if document_context else (
        'Not requested — do not invent document contents.'
    )
    live_section = live_context if live_context else 'No live data available.'
    history_section = history if history else 'No earlier messages in this conversation.'
    return f"""You are the in-app assistant for the university QA Archiving System web application.

STRICT RULES:
1. Answer ONLY about this application's features, pages, workflows, and the LIVE SYSTEM DATA below.
2. If the question is unrelated (general trivia, homework, coding, weather, etc.), reply exactly:
   "I can only help with this QA Archiving System. Ask about uploads, repository, search, area submissions, reports, or say help me navigate."
3. Use ONLY page and sidebar names from SYSTEM KNOWLEDGE below — never invent menus or paste URLs.
4. Be concise: 2–6 sentences unless the user asks for steps.
5. Plain text only (no Markdown headings or bullet symbols like # or *).
6. Document snippets are optional context — use them ONLY if they directly answer a question about archived file content.
7. LIVE SYSTEM DATA reflects the real current state — use it for questions about counts, status, or progress, and never invent numbers that are not listed there.
8. Use CONVERSATION SO FAR to resolve follow-up questions (e.g. "what about duplicates?").

SYSTEM KNOWLEDGE (authoritative):
{nav_block}

LIVE SYSTEM DATA (current, permission-scoped to this user):
{live_section}

OPTIONAL UPLOADED DOCUMENT SNIPPETS:
{doc_section}

CONVERSATION SO FAR:
{history_section}

USER QUESTION:
{user_message}

ASSISTANT ANSWER:"""

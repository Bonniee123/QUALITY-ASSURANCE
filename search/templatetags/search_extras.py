"""Template filters for smart search presentation."""
import re

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()


def _highlight_tokens(escaped_text, query):
    tokens = sorted(
        {t for t in re.findall(r'[a-z0-9]+', (query or '').lower()) if len(t) > 1},
        key=len,
        reverse=True,
    )
    if not tokens:
        phrase = (query or '').strip()
        if len(phrase) >= 2:
            tokens = [re.escape(phrase)]
        else:
            return escaped_text
    else:
        tokens = [re.escape(t) for t in tokens]

    pattern = re.compile('|'.join(tokens), re.IGNORECASE)
    return pattern.sub(lambda m: f'<mark class="srch-hl">{m.group(0)}</mark>', escaped_text)


@register.filter(name='highlight_terms')
def highlight_terms(text, query):
    """Escape HTML, then wrap query token matches in <mark>."""
    if text is None:
        return ''
    if not query:
        return conditional_escape(text)
    escaped = conditional_escape(str(text))
    return mark_safe(_highlight_tokens(escaped, str(query)))


@register.filter(name='match_field_label')
def match_field_label(reason):
    """Map explain_match reason strings to short badge labels."""
    mapping = {
        'title': 'Title',
        'description': 'Description',
        'ocr text': 'OCR',
        'extracted text': 'Content',
        'keywords': 'Keyword',
        'document type': 'Metadata',
        'QA area': 'Metadata',
        'accreditation area': 'Accreditation',
        'parameter': 'Parameter',
        'indicator': 'Indicator',
    }
    return mapping.get(reason, reason.title())

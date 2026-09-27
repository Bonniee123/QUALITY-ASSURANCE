"""Domain stopwords for QA / accreditation document clustering."""
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# Generic QA boilerplate that should not drive cluster membership.
QA_DOMAIN_STOPWORDS = {
    'accreditation', 'accredited', 'accrediting', 'aaccup', 'university', 'college',
    'institution', 'institutional', 'campus', 'department', 'office', 'document',
    'documents', 'file', 'files', 'page', 'pages', 'section', 'sections',
    'appendix', 'attachment', 'attachments', 'form', 'forms', 'report', 'reports',
    'policy', 'policies', 'manual', 'manuals', 'quality', 'assurance',
    'compliance', 'standard', 'standards', 'requirement', 'requirements',
    'evidence', 'indicator', 'indicators', 'criterion', 'criteria', 'area',
    'program', 'programs', 'school', 'faculty', 'student', 'students',
    'academic', 'year', 'semester', 'prepared', 'submitted', 'approved',
    'revision', 'revised', 'date', 'signed', 'copy', 'original', 'reference',
    'table', 'contents', 'introduction', 'overview', 'summary', 'annex',
}


def clustering_stop_words():
    """English + QA domain stopwords for TF-IDF clustering (not keyword extraction)."""
    return list(ENGLISH_STOP_WORDS | QA_DOMAIN_STOPWORDS)

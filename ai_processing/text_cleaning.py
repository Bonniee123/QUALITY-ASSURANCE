"""
Text cleaning utilities for NLP preprocessing.
Cleans extracted text before TF-IDF and clustering.
"""
import re
import string


def clean_text(text):
    """
    Clean and normalize text for NLP processing.
    - Convert to lowercase
    - Remove special characters and excessive whitespace
    - Remove numbers-only tokens
    - Strip punctuation edges
    """
    if not text:
        return ''

    # Convert to lowercase
    text = text.lower()

    # Remove URLs
    text = re.sub(r'http\S+|www\.\S+', '', text)

    # Remove email addresses
    text = re.sub(r'\S+@\S+', '', text)

    # Remove special characters but keep spaces and basic punctuation
    text = re.sub(r'[^\w\s]', ' ', text)

    # Remove standalone numbers
    text = re.sub(r'\b\d+\b', '', text)

    # Collapse multiple whitespace into single space
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def tokenize_text(text):
    """Split cleaned text into word tokens."""
    if not text:
        return []
    return text.split()


def remove_stopwords(tokens, extra_stopwords=None):
    """
    Remove common English stopwords from token list.
    Includes a basic stopword set without requiring NLTK.
    """
    stopwords = {
        'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
        'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'shall', 'can', 'need', 'dare',
        'it', 'its', 'this', 'that', 'these', 'those', 'i', 'me', 'my',
        'we', 'our', 'you', 'your', 'he', 'she', 'they', 'them', 'their',
        'what', 'which', 'who', 'whom', 'when', 'where', 'why', 'how',
        'not', 'no', 'nor', 'as', 'if', 'then', 'than', 'too', 'very',
        'just', 'about', 'above', 'after', 'again', 'all', 'also', 'any',
        'because', 'before', 'between', 'both', 'each', 'few', 'more',
        'most', 'other', 'over', 'same', 'so', 'some', 'such', 'through',
        'under', 'until', 'up', 'while', 'into', 'during', 'out', 'off',
    }
    if extra_stopwords:
        stopwords.update(extra_stopwords)

    return [t for t in tokens if t not in stopwords and len(t) > 2]

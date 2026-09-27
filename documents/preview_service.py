"""Faithful in-browser previews for Office documents."""
import hashlib
import logging
import os

from django.conf import settings

from .preview_converters import (
    convert_docx_to_pdf,
    has_faithful_docx_converter,
)

logger = logging.getLogger(__name__)

PDF_PREVIEW_FILE_TYPES = frozenset({'docx'})
# Bump when converter logic changes so stale low-fidelity caches are ignored.
_CACHE_VERSION = 'v2'


def uses_pdf_preview(file_type):
    return (file_type or '').lower() in PDF_PREVIEW_FILE_TYPES


def prefer_docx_js_preview():
    """
    When True, DOCX files use the browser docx-preview renderer (keeps Word fonts,
    header logos, alignment) instead of a low-fidelity PyMuPDF PDF.
    """
    mode = getattr(settings, 'DOCX_PREVIEW_MODE', 'auto').strip().lower()
    if mode == 'docx':
        return True
    if mode == 'pdf':
        return False
    return not has_faithful_docx_converter()


def _preview_cache_dir():
    root = getattr(settings, 'MEDIA_ROOT', 'media')
    path = os.path.join(root, 'preview_cache')
    os.makedirs(path, exist_ok=True)
    return path


def _source_token(file_path):
    stat = os.stat(file_path)
    raw = f'{_CACHE_VERSION}|{file_path}|{stat.st_mtime_ns}|{stat.st_size}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def preview_cache_path(document):
    token = _source_token(document.file.path)
    return os.path.join(_preview_cache_dir(), f'doc_{document.pk}_{token}.pdf')


def build_pdf_preview(document):
    """Return path to a cached PDF preview. Raises on failure."""
    if not document.file:
        raise FileNotFoundError('Document has no file.')
    source_path = document.file.path
    if not os.path.isfile(source_path):
        raise FileNotFoundError('Source file missing on disk.')
    if not uses_pdf_preview(document.file_type):
        raise ValueError(f'Preview conversion not supported for {document.file_type}')

    cache_path = preview_cache_path(document)
    if os.path.isfile(cache_path):
        return cache_path

    ok, engine = convert_docx_to_pdf(source_path, cache_path)
    if not ok:
        raise RuntimeError('Could not convert document to PDF for preview.')
    logger.info('Built PDF preview for document #%s via %s', document.pk, engine)
    return cache_path


def clear_preview_cache(document=None):
    """Remove cached preview PDFs (one document or all)."""
    cache_dir = _preview_cache_dir()
    if document is None:
        for name in os.listdir(cache_dir):
            if name.endswith('.pdf'):
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
        return
    prefix = f'doc_{document.pk}_'
    for name in os.listdir(cache_dir):
        if name.startswith(prefix) and name.endswith('.pdf'):
            try:
                os.remove(os.path.join(cache_dir, name))
            except OSError:
                pass

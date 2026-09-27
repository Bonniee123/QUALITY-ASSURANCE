"""DOCX → PDF converters — prefer engines that preserve headers, logos, and Word layout."""
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def find_libreoffice():
    """Return path to LibreOffice soffice binary, or None."""
    env_path = (os.environ.get('LIBREOFFICE_PATH') or '').strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    candidates = [
        r'C:\Program Files\LibreOffice\program\soffice.exe',
        r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
        '/usr/bin/libreoffice',
        '/usr/bin/soffice',
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    for name in ('soffice', 'libreoffice'):
        found = shutil.which(name)
        if found:
            return found
    return None


def has_faithful_docx_converter():
    """True when LibreOffice or Microsoft Word conversion is available."""
    if find_libreoffice():
        return True
    return _word_com_available()


def _word_com_available():
    try:
        import docx2pdf  # noqa: F401
    except ImportError:
        return False
    if os.name != 'nt':
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def convert_docx_to_pdf_libreoffice(source_path, dest_pdf):
    soffice = find_libreoffice()
    if not soffice:
        return False
    out_dir = tempfile.mkdtemp(prefix='qa_lo_pdf_')
    try:
        result = subprocess.run(
            [
                soffice,
                '--headless',
                '--norestore',
                '--invisible',
                '--convert-to',
                'pdf',
                '--outdir',
                out_dir,
                source_path,
            ],
            capture_output=True,
            timeout=int(os.environ.get('LIBREOFFICE_CONVERT_TIMEOUT', '180')),
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                'LibreOffice conversion failed (code %s): %s',
                result.returncode,
                (result.stderr or b'').decode('utf-8', errors='replace')[:500],
            )
            return False
        produced = os.path.join(out_dir, os.path.splitext(os.path.basename(source_path))[0] + '.pdf')
        if not os.path.isfile(produced) or os.path.getsize(produced) < 32:
            return False
        os.makedirs(os.path.dirname(dest_pdf), exist_ok=True)
        shutil.move(produced, dest_pdf)
        return True
    except Exception as exc:
        logger.warning('LibreOffice conversion error: %s', exc)
        return False
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def convert_docx_to_pdf_word(source_path, dest_pdf):
    if not _word_com_available():
        return False
    try:
        from docx2pdf import convert

        os.makedirs(os.path.dirname(dest_pdf), exist_ok=True)
        convert(source_path, dest_pdf)
        ok = os.path.isfile(dest_pdf) and os.path.getsize(dest_pdf) > 32
        if not ok:
            logger.warning('Word COM conversion produced no PDF for %s', source_path)
        return ok
    except Exception as exc:
        logger.warning('Word COM conversion error: %s', exc)
        return False


def convert_docx_to_pdf_pymupdf(source_path, dest_pdf):
    """
    Fast fallback — text layout only; often drops header/footer logos.
    Use only when no faithful converter is available.
    """
    try:
        import pymupdf
    except ImportError:
        return False
    try:
        src = pymupdf.open(source_path)
        try:
            pdf_bytes = src.convert_to_pdf()
        finally:
            src.close()
        if not pdf_bytes:
            return False
        os.makedirs(os.path.dirname(dest_pdf), exist_ok=True)
        with open(dest_pdf, 'wb') as handle:
            handle.write(pdf_bytes)
        return True
    except Exception as exc:
        logger.warning('PyMuPDF conversion error: %s', exc)
        return False


def convert_docx_to_pdf(source_path, dest_pdf):
    """
    Convert DOCX to PDF using the best available engine.
    Returns (success, engine_name).
    """
    for name, func in (
        ('libreoffice', convert_docx_to_pdf_libreoffice),
        ('word', convert_docx_to_pdf_word),
        ('pymupdf', convert_docx_to_pdf_pymupdf),
    ):
        tmp = f'{dest_pdf}.tmp'
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        try:
            if func(source_path, tmp):
                os.replace(tmp, dest_pdf)
                return True, name
        except Exception as exc:
            logger.warning('%s converter raised: %s', name, exc)
        finally:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return False, ''

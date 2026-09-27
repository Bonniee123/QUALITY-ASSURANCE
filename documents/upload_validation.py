"""
Is an upload's content what its extension says it is?

Uploads were accepted on the extension alone: a Windows program and an HTML page
renamed to ".pdf" were stored and served as PDFs, and an empty file was accepted
and then failed in the background with nothing to show for it. Every upload path
-- bulk, Faculty single-file and structured -- asks this before saving.

What a file has to survive to be stored:

1. it is not empty (the caller checks the size limit before asking);
2. the type the browser declared is not one we never accept -- a page or a
   program offered as a ".pdf" is refused on that alone;
3. its first bytes are the signature of the extension it claims;
4. an image must actually decode as that format and stay inside a pixel budget:
   a file can carry a correct PNG header and still be broken or hostile, and a
   small image declaring enormous dimensions is a decompression bomb;
5. a Word or Excel file must be a real Office package -- the expected parts, no
   macro project, no entry climbing out of the package, no absurd expansion.

Nothing here runs or renders the upload. It reads the header, and for images and
Office packages the structure, which is the part an attacker controls.
"""
import io
import os
import posixpath
import zipfile

from PIL import Image

# The bytes each accepted format starts with.
_SIGNATURES = {
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.docx': (b'PK\x03\x04',),
    '.xlsx': (b'PK\x03\x04',),
}

# The part every Word document / Excel workbook contains (both are ZIP packages).
_OFFICE_PART = {'.docx': 'word/', '.xlsx': 'xl/'}

_NAMES = {'.pdf': 'PDF', '.png': 'PNG image', '.jpg': 'JPEG image', '.jpeg': 'JPEG image',
          '.docx': 'Word document', '.xlsx': 'Excel workbook'}

# What Pillow must report for an image to count as the extension it claims.
_IMAGE_FORMATS = {'.png': {'PNG'}, '.jpg': {'JPEG'}, '.jpeg': {'JPEG'}}

# Decoding is where an image costs memory, so the budget is in pixels rather than
# bytes: a 2 MB PNG can declare 30000x30000 and ask for gigabytes when opened.
_MAX_IMAGE_PIXELS = 50_000_000

# An Office package is a ZIP, and a ZIP can promise far more than it carries.
_MAX_OFFICE_UNPACKED = 400 * 1024 * 1024
_OFFICE_RATIO_LIMIT = 200
_OFFICE_RATIO_FLOOR = 50 * 1024 * 1024  # small packages compress very well; only judge big ones

# Types we never store, whatever the extension claims. The browser's word is not
# evidence, but a file *offered* as one of these is refused without reading it.
_REFUSED_DECLARED_TYPES = {
    'text/html', 'text/javascript', 'application/javascript', 'application/x-javascript',
    'image/svg+xml', 'application/x-msdownload', 'application/x-msdos-program',
    'application/x-executable', 'application/x-dosexec', 'application/x-sh',
    'application/x-shellscript', 'application/x-httpd-php', 'text/x-php',
    'application/x-bat', 'application/x-msi',
}

_READ_LIMIT = 32 * 1024 * 1024  # headroom over the 25 MB upload cap the callers enforce


def _declared_type(uploaded_file):
    """The media type the browser attached to this upload, bare and lowercase."""
    declared = getattr(uploaded_file, 'content_type', '') or ''
    return declared.split(';')[0].strip().lower()


def _image_problem(data, ext, kind):
    """Why these bytes are not a usable `ext` image, or ''."""
    try:
        image = Image.open(io.BytesIO(data))
        fmt, (width, height) = image.format, image.size
        image.verify()  # walks the file's structure; the object is spent afterwards
    except Image.DecompressionBombError:
        return 'the image is too large to open safely'
    except Exception:
        return f'the file is not a real {kind} (it could not be opened as an image)'
    if fmt not in _IMAGE_FORMATS.get(ext, set()):
        return f'the file is not a real {kind} (it is {fmt or "an unknown format"} inside)'
    if width * height > _MAX_IMAGE_PIXELS:
        return f'the image is too large to open safely ({width}x{height} pixels)'
    return ''


def _office_problem(uploaded_file, ext, kind):
    """Why this package is not a usable `ext` file, or ''."""
    mismatch = f'the file is not a real {kind} (its content does not match the {ext} extension)'
    try:
        uploaded_file.seek(0)
        with zipfile.ZipFile(uploaded_file) as package:
            members = package.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return mismatch

    names = [m.filename for m in members]
    if '[Content_Types].xml' not in names or not any(n.startswith(_OFFICE_PART[ext]) for n in names):
        return mismatch

    for name in names:
        # A real package holds plain relative parts. An entry climbing out of the
        # folder is how an unpacking tool is tricked into writing somewhere else.
        if name.startswith('/') or '\\' in name or os.path.isabs(name) \
                or '..' in posixpath.normpath(name).split('/'):
            return f'the file is not a real {kind} (it contains an unsafe entry: {name[:60]})'
        if posixpath.basename(name).lower() == 'vbaproject.bin':
            return f'macro-enabled {kind}s are not accepted; save it without macros and upload again'

    unpacked = sum(m.file_size for m in members)
    packed = sum(m.compress_size for m in members) or 1
    if unpacked > _MAX_OFFICE_UNPACKED or (
            unpacked > _OFFICE_RATIO_FLOOR and unpacked / packed > _OFFICE_RATIO_LIMIT):
        return 'the file expands to far more than it appears to hold and was refused'
    return ''


def upload_content_problem(uploaded_file, ext):
    """
    Why this file cannot be stored as `ext`, or '' when its content matches.

    Reads the header, the picture itself for images, and the ZIP directory for
    Word and Excel, and leaves the file positioned at the start for the caller.
    """
    ext = (ext or '').lower()
    if not ext.startswith('.'):
        ext = f'.{ext}'
    if not getattr(uploaded_file, 'size', 0):
        return 'the file is empty'
    kind = _NAMES.get(ext, ext.lstrip('.').upper())

    # Only outright dangerous types are judged here. "text/plain" and
    # "application/octet-stream" are what a client sends when it does not
    # recognise a file, so refusing those would refuse honest uploads; the
    # content checks below are the real gate.
    declared = _declared_type(uploaded_file)
    if declared in _REFUSED_DECLARED_TYPES:
        return f'the browser offered this file as {declared}, which is not accepted as a {kind}'

    mismatch = f'the file is not a real {kind} (its content does not match the {ext} extension)'
    problem = ''
    try:
        uploaded_file.seek(0)
        head = uploaded_file.read(1024)
        if ext == '.pdf':
            # The PDF header may follow a little leading junk; readers accept that.
            matches = b'%PDF-' in head
        else:
            matches = head.startswith(_SIGNATURES.get(ext, (b'',)))
        if not matches:
            problem = mismatch
        elif ext in _IMAGE_FORMATS:
            uploaded_file.seek(0)
            problem = _image_problem(uploaded_file.read(_READ_LIMIT), ext, kind)
        elif ext in _OFFICE_PART:
            problem = _office_problem(uploaded_file, ext, kind)
    except (OSError, ValueError):
        problem = mismatch
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    return problem

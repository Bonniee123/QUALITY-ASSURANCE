"""
What may be sent as a message attachment, and how it is checked and stored.

The same rule as every other upload in the system: the extension decides what a
file may claim to be, and the content must then prove it. The type a file is
served with afterwards comes from this table, never from what the browser said.

Three kinds:

* pictures (PNG, JPEG, GIF, WebP) -- shown in the conversation from a re-encoded
  thumbnail, which also drops the photo's metadata (camera, location);
* voice messages recorded in the browser (WebM/Opus, Ogg, MP4/AAC, MP3, WAV);
* files: PDF, Word, Excel, PowerPoint, plain text and CSV -- always downloaded,
  never opened inside the system's own pages.

Nothing here runs or renders a file.
"""
from __future__ import annotations

import io
import os
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from documents.upload_validation import _REFUSED_DECLARED_TYPES, upload_content_problem

IMAGE_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp',
}
FILE_TYPES = {
    '.pdf': 'application/pdf',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain; charset=utf-8',
    '.csv': 'text/csv; charset=utf-8',
}
VOICE_TYPES = {
    '.webm': 'audio/webm', '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg',
    '.m4a': 'audio/mp4', '.mp4': 'audio/mp4', '.aac': 'audio/aac',
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
}

ALLOWED_DESCRIPTION = 'pictures (PNG, JPG, GIF, WebP), PDF, Word, Excel, PowerPoint, text and CSV files'

_MAX_IMAGE_PIXELS = 50_000_000
_THUMB_EDGE = 720


def max_bytes() -> int:
    return int(getattr(settings, 'MESSAGE_ATTACHMENT_MAX_MB', 15)) * 1024 * 1024


def max_files() -> int:
    return int(getattr(settings, 'MESSAGE_ATTACHMENTS_PER_MESSAGE', 10))


class AttachmentError(Exception):
    """Why a file cannot be sent. `code` lets the page word it: invalid_type, too_large, too_many, empty."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _declared(uploaded):
    return (getattr(uploaded, 'content_type', '') or '').split(';')[0].strip().lower()


def _head(uploaded, n=64):
    uploaded.seek(0)
    data = uploaded.read(n)
    uploaded.seek(0)
    return data


def _image_info(uploaded, ext):
    """(width, height) of a real picture of this type, or raise."""
    expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.gif': 'GIF', '.webp': 'WEBP'}[ext]
    try:
        uploaded.seek(0)
        image = Image.open(uploaded)
        fmt, (width, height) = image.format, image.size
        image.verify()
    except Image.DecompressionBombError:
        raise AttachmentError('invalid_type', 'the picture is too large to open safely')
    except Exception:
        raise AttachmentError('invalid_type', 'the file is not a real picture')
    finally:
        uploaded.seek(0)
    if fmt != expected:
        raise AttachmentError('invalid_type', f'the file is not a real {ext.lstrip(".").upper()} picture')
    if width * height > _MAX_IMAGE_PIXELS:
        raise AttachmentError('invalid_type', f'the picture is too large to open safely ({width}x{height})')
    return width, height


def _pptx_problem(uploaded):
    try:
        uploaded.seek(0)
        with zipfile.ZipFile(uploaded) as package:
            names = package.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return 'the file is not a real PowerPoint presentation'
    finally:
        uploaded.seek(0)
    if '[Content_Types].xml' not in names or not any(n.startswith('ppt/') for n in names):
        return 'the file is not a real PowerPoint presentation'
    if any(os.path.basename(n).lower() == 'vbaproject.bin' for n in names):
        return 'presentations with macros are not accepted; save it without macros and send again'
    if any(n.startswith('/') or '..' in n.split('/') for n in names):
        return 'the file is not a real PowerPoint presentation (it contains an unsafe entry)'
    return ''


def _text_problem(uploaded):
    uploaded.seek(0)
    sample = uploaded.read(65536)
    uploaded.seek(0)
    if b'\x00' in sample:
        return 'the file is not plain text'
    return ''


def _voice_matches(head, ext):
    if ext == '.webm':
        return head.startswith(b'\x1a\x45\xdf\xa3')
    if ext in ('.ogg', '.oga', '.opus'):
        return head.startswith(b'OggS')
    if ext in ('.m4a', '.mp4'):
        return head[4:8] == b'ftyp'
    if ext == '.aac':
        return head[:2] in (b'\xff\xf1', b'\xff\xf9')
    if ext == '.mp3':
        return head.startswith(b'ID3') or head[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')
    if ext == '.wav':
        return head.startswith(b'RIFF') and head[8:12] == b'WAVE'
    return False


def check(uploaded, *, voice=False):
    """
    Decide what this upload is. Returns (kind, content_type, width, height),
    or raises AttachmentError saying why it cannot be sent.
    """
    name = os.path.basename(getattr(uploaded, 'name', '') or 'file')
    ext = os.path.splitext(name)[1].lower()
    size = getattr(uploaded, 'size', 0) or 0
    if not size:
        raise AttachmentError('empty', f'“{name}” is empty')
    if size > max_bytes():
        raise AttachmentError('too_large', f'“{name}” is larger than {max_bytes() // (1024 * 1024)} MB')
    if _declared(uploaded) in _REFUSED_DECLARED_TYPES:
        raise AttachmentError('invalid_type', f'“{name}” cannot be sent: that type of file is never accepted')

    if voice:
        if ext not in VOICE_TYPES or not _voice_matches(_head(uploaded, 16), ext):
            raise AttachmentError('invalid_type', 'the recording is not in an audio format this system accepts')
        from .models import MessageAttachment
        return MessageAttachment.KIND_VOICE, VOICE_TYPES[ext], None, None

    from .models import MessageAttachment
    if ext in IMAGE_TYPES:
        if ext in ('.png', '.jpg', '.jpeg'):
            problem = upload_content_problem(uploaded, ext)
            if problem:
                raise AttachmentError('invalid_type', f'“{name}”: {problem}')
        width, height = _image_info(uploaded, ext)
        return MessageAttachment.KIND_IMAGE, IMAGE_TYPES[ext], width, height

    if ext in FILE_TYPES:
        if ext in ('.pdf', '.docx', '.xlsx'):
            problem = upload_content_problem(uploaded, ext)
        elif ext == '.pptx':
            problem = _pptx_problem(uploaded)
        else:
            problem = _text_problem(uploaded)
        if problem:
            raise AttachmentError('invalid_type', f'“{name}”: {problem}')
        return MessageAttachment.KIND_FILE, FILE_TYPES[ext], None, None

    raise AttachmentError('invalid_type', f'“{name}” cannot be sent. You can send {ALLOWED_DESCRIPTION}.')


def thumbnail_for(uploaded):
    """A re-encoded copy of a picture, at most 720px on its longest side, as (ContentFile, ext)."""
    uploaded.seek(0)
    try:
        image = Image.open(uploaded)
        image = ImageOps.exif_transpose(image)  # respect the camera's rotation, then drop the metadata
        image.thumbnail((_THUMB_EDGE, _THUMB_EDGE))
        out = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGBA')
            image.save(out, format='PNG', optimize=True)
            ext = '.png'
        else:
            image.convert('RGB').save(out, format='JPEG', quality=82, optimize=True)
            ext = '.jpg'
    except Exception:
        return None, ''
    finally:
        uploaded.seek(0)
    return ContentFile(out.getvalue()), ext


def describe(kinds) -> str:
    """What a message with these attachments contains, for previews and notifications."""
    kinds = list(kinds)
    if not kinds:
        return ''
    from .models import MessageAttachment
    if all(k == MessageAttachment.KIND_IMAGE for k in kinds):
        return 'a photo' if len(kinds) == 1 else f'{len(kinds)} photos'
    if kinds == [MessageAttachment.KIND_VOICE]:
        return 'a voice message'
    return 'a file' if len(kinds) == 1 else f'{len(kinds)} files'

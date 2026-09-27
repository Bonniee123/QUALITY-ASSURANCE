"""
Optional semantic embeddings for document clustering.
Requires: pip install sentence-transformers
Falls back gracefully when the package or model is unavailable.
"""
import errno
import hashlib
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

logger = logging.getLogger(__name__)

_model_cache = {}
_model_lock = threading.Lock()

# Vectors for text already encoded, keyed by model and a hash of the exact text
# that was encoded. Every clustering run reads the whole corpus, but only new or
# changed documents need encoding -- the rest reuse the vector they already had.
# Bounded so a long-running server cannot grow it without limit (20,000 vectors
# of 384 floats is about 30 MB).
_vector_cache = OrderedDict()
_vector_lock = threading.Lock()
_VECTOR_CACHE_MAX = 20000

# The model is loaded and run on this one thread only. PyTorch's math library
# starts a team of worker threads for every thread that calls into it, and on
# Windows a team outlives the thread that started it. Clustering after each
# upload runs on a fresh thread, so every upload left about 7 threads and 70 MB
# behind for good: a test server grew from 1.5 GB to 4 GB over a day of uploads
# and ran out of memory. One long-lived thread means one team, reused.
_model_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qa-embedding')


def _on_model_thread(fn, *args, **kwargs):
    return _model_thread.submit(fn, *args, **kwargs).result()


_MB = 1024 * 1024

# ------------------------------------------------------------- memory guard
#
# Loading the model takes about 730 MB on top of what the server already uses
# (measured: 250 MB to import torch, 135 MB for the model itself, up to 340 MB
# more while encoding). When the PC cannot supply that -- RAM full and the page
# file unable to grow -- the load does not always fail politely: it can crash
# the whole Python process, and clustering runs inside the web server, so the
# server goes down with it. Clustering already falls back to TF-IDF whenever
# embeddings are unavailable, so the safe move is to look before loading and,
# if memory is short, skip the model for this run. The next run looks again.

# Windows errors that mean "out of memory": not enough memory, out of memory,
# and "the paging file is too small for this operation to complete".
_OUT_OF_MEMORY_WINERRORS = {8, 14, 1455}
_OUT_OF_MEMORY_TEXT = ('paging file is too small', 'os error 1455', 'not enough memory', 'out of memory')

# Free space a drive keeps back before its page file is counted as able to grow
# into the rest.
_PAGE_FILE_DISK_RESERVE_MB = 1024


def _ran_out_of_memory(exc):
    """True when an exception, or anything that caused it, is the PC running out of memory."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, MemoryError):
            return True
        if isinstance(exc, OSError) and (
            getattr(exc, 'winerror', None) in _OUT_OF_MEMORY_WINERRORS or exc.errno == errno.ENOMEM
        ):
            return True
        # Errors raised from Rust or C++ code (safetensors, torch) carry the
        # Windows error in the message only.
        text = str(exc).lower()
        if any(phrase in text for phrase in _OUT_OF_MEMORY_TEXT):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _windows_memory():
    """(RAM, commit limit, commit available) in MB, from GlobalMemoryStatusEx; None if the call fails."""
    import ctypes
    from ctypes import wintypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ('dwLength', wintypes.DWORD),
            ('dwMemoryLoad', wintypes.DWORD),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    # "Page file" in these names is Windows' word for the commit limit: RAM plus
    # every page file in use. Available is what this process could still commit.
    return status.ullTotalPhys // _MB, status.ullTotalPageFile // _MB, status.ullAvailPageFile // _MB


def _page_file_growth_mb(entry, current_mb, active_mb, ram_mb, volume_mb, free_mb):
    """
    How far the system drive's page file can still grow, in MB.

    `entry` is its line in the PagingFiles registry value: "c:\\pagefile.sys 0 0"
    (system managed), "?:\\pagefile.sys" (Windows manages every drive), or
    "c:\\pagefile.sys 1024 4096" (initial and maximum size in MB). Microsoft's
    rule for a system-managed page file: it grows to 3 x RAM or 4 GB, whichever
    is larger, but no more than an eighth of the drive -- and only into free
    space. `active_mb` is how much page file Windows is using in total (commit
    limit minus RAM); a file bigger than that is on disk but not the one in
    use, so it cannot be counted on to grow.
    """
    if not entry or current_mb <= 0 or active_mb < current_mb - 64:
        return 0
    parts = entry.split()
    if len(parts) == 1 or parts[1:3] == ['0', '0']:
        maximum_mb = min(max(3 * ram_mb, 4096), volume_mb // 8)
    else:
        try:
            maximum_mb = int(parts[2])
        except (IndexError, ValueError):
            return 0
    return max(0, min(maximum_mb - current_mb, free_mb - _PAGE_FILE_DISK_RESERVE_MB))


def _system_page_file_growth_mb(ram_mb, commit_limit_mb):
    """Read the system drive's page file setting, size and free space, and work out its room to grow."""
    import shutil
    import winreg

    drive = os.environ.get('SystemDrive', 'C:').upper()
    key_path = r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
        configured, _kind = winreg.QueryValueEx(key, 'PagingFiles')
    if isinstance(configured, str):
        configured = [configured]
    entry = next((line for line in configured if line[:2].upper() in (drive, '?:')), None)
    if not entry:
        return 0
    path = entry.split()[0]
    if path.startswith('?:'):
        path = drive + path[2:]
    try:
        current_mb = os.stat(path).st_size // _MB
    except OSError:
        return 0
    disk = shutil.disk_usage(drive + '\\')
    return _page_file_growth_mb(
        entry, current_mb, commit_limit_mb - ram_mb, ram_mb, disk.total // _MB, disk.free // _MB,
    )


def _free_memory_mb():
    """
    Memory this process could still get, in MB: what is free now plus the room
    the page file has to grow. None where it cannot be told (not Windows).
    """
    if os.name != 'nt':
        return None
    try:
        memory = _windows_memory()
    except Exception:
        return None
    if memory is None:
        return None
    ram_mb, commit_limit_mb, available_mb = memory
    try:
        growth_mb = _system_page_file_growth_mb(ram_mb, commit_limit_mb)
    except Exception:
        growth_mb = 0  # cannot tell: count only what is free right now
    return available_mb + growth_mb


def _enough_memory_for_model(model_name):
    needed_mb = int(getattr(settings, 'AI_CLUSTER_EMBEDDING_MIN_FREE_MB', 1536))
    if needed_mb <= 0:
        return True
    free_mb = _free_memory_mb()
    if free_mb is None or free_mb >= needed_mb:
        return True
    logger.warning(
        'Not loading the embedding model %s: %s MB of memory free, %s MB wanted '
        '(AI_CLUSTER_EMBEDDING_MIN_FREE_MB). Clustering with TF-IDF this time instead.',
        model_name, free_mb, needed_mb,
    )
    return False


def _load_model(model_name):
    from sentence_transformers import SentenceTransformer

    try:
        # The model is normally on disk already. Loading it from local files
        # skips Hugging Face's online checks, which measured about 85 seconds on
        # this network before loading could even begin -- paid by the first
        # clustering run after every server restart.
        return SentenceTransformer(model_name, local_files_only=True)
    except Exception as exc:
        if _ran_out_of_memory(exc):
            # The files are here; the memory is not. Going online would only
            # repeat the same load after a slow network check.
            raise
        # Not cached yet (a fresh machine): fetch it once, exactly as before.
        logger.info('Embedding model %s not available locally (%s); loading online.', model_name, exc)
        return SentenceTransformer(model_name)


def _text_key(model_name, text):
    return model_name, hashlib.sha1(text.encode('utf-8', 'surrogatepass')).hexdigest()


def compute_embedding_matrix(documents):
    """
    Encode documents with a sentence-transformer model.
    Returns a dense numpy matrix (n_docs x dim) or None on failure.
    """
    model_name = getattr(
        settings,
        'AI_CLUSTER_EMBEDDING_MODEL',
        'all-MiniLM-L6-v2',
    )
    # Looked at before sentence-transformers is even imported: importing torch
    # is a third of the cost. A model already loaded needs no new memory.
    if model_name not in _model_cache and not _enough_memory_for_model(model_name):
        return None

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        import numpy as np
    except Exception as exc:
        # Not just ImportError: importing torch can also fail with OSError when the
        # package files are unreadable (e.g. cloud-only OneDrive files, or a full
        # disk). Clustering must still fall back to TF-IDF rather than crash.
        logger.info('sentence-transformers unavailable (%s); embedding clustering skipped.', exc)
        return None

    from ai_processing.clustering_text import clustering_input_text

    max_chars = int(getattr(settings, 'AI_CLUSTER_EMBEDDING_MAX_CHARS', 12000))

    try:
        with _model_lock:
            if model_name not in _model_cache:
                _model_cache[model_name] = _on_model_thread(_load_model, model_name)
            model = _model_cache[model_name]
    except Exception as exc:
        logger.warning('Could not load embedding model %s: %s', model_name, exc)
        return None

    texts = [clustering_input_text(doc)[:max_chars] for doc in documents]
    keys = [_text_key(model_name, text) for text in texts]

    with _vector_lock:
        vectors = {key: _vector_cache[key] for key in keys if key in _vector_cache}

    # Only text never seen before is encoded, and each distinct text once.
    missing = OrderedDict()
    for key, text in zip(keys, texts):
        if key not in vectors:
            missing.setdefault(key, text)

    if missing:
        try:
            encoded = _on_model_thread(
                model.encode,
                list(missing.values()),
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            logger.warning('Embedding encode failed: %s', exc)
            return None
        with _vector_lock:
            for key, vector in zip(missing, encoded):
                vectors[key] = vector
                _vector_cache[key] = vector
                _vector_cache.move_to_end(key)
            while len(_vector_cache) > _VECTOR_CACHE_MAX:
                _vector_cache.popitem(last=False)

    return np.asarray([vectors[key] for key in keys])

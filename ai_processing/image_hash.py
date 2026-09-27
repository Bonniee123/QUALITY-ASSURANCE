"""
Perceptual image hashing (difference hash / dHash) for visual near-duplicate detection.

This catches images that *look* alike even when they contain little or no OCR text,
complementing the text-based (TF-IDF / SequenceMatcher) duplicate detection.

Implemented with Pillow + numpy only (both already required) — no extra dependencies.
A 64-bit dHash is stored as a 16-character hex string. Two images are considered
visually similar when the Hamming distance between their hashes is small.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

HASH_SIZE = 8                       # 8x8 comparison grid -> 64 bits
HASH_BITS = HASH_SIZE * HASH_SIZE
HASH_HEX_LEN = HASH_BITS // 4       # 16 hex chars

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp', 'tiff', 'tif'}


def is_image_file(file_type_or_ext):
    """True when the given extension / file_type is a supported raster image."""
    if not file_type_or_ext:
        return False
    return str(file_type_or_ext).lower().lstrip('.') in IMAGE_EXTENSIONS


def compute_image_hash(file_path):
    """
    Compute a 64-bit difference hash for an image.

    Returns a 16-character hex string, or '' if the file cannot be hashed
    (missing Pillow/numpy, unreadable file, non-image, etc.).
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(file_path) as img:
            # Respect EXIF orientation so rotated copies still match.
            img = ImageOps.exif_transpose(img)
            img = img.convert('L').resize((HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS)
            pixels = np.asarray(img, dtype=np.int16)

        # Horizontal gradient: each pixel brighter than its right neighbour -> 1 bit.
        diff = pixels[:, 1:] > pixels[:, :-1]
        value = 0
        for bit in diff.flatten():
            value = (value << 1) | int(bool(bit))
        return format(value, '0{}x'.format(HASH_HEX_LEN))
    except Exception as e:  # noqa: BLE001 - hashing is best-effort
        logger.info('Image hash failed for %s: %s', file_path, e)
        return ''


def hamming_distance(hash_a, hash_b):
    """Number of differing bits between two hex hashes, or None if not comparable."""
    if not hash_a or not hash_b or len(hash_a) != len(hash_b):
        return None
    try:
        return bin(int(hash_a, 16) ^ int(hash_b, 16)).count('1')
    except ValueError:
        return None


def visual_similarity(hash_a, hash_b):
    """Similarity in the 0..1 range (1.0 = identical), or None if not comparable."""
    dist = hamming_distance(hash_a, hash_b)
    if dist is None:
        return None
    return 1.0 - (dist / HASH_BITS)


def max_distance():
    """Configurable Hamming-distance cutoff for treating two images as duplicates."""
    return int(getattr(settings, 'IMAGE_PHASH_MAX_DISTANCE', 10))


def duplicate_mean_cutoff() -> float:
    """Mean pixel difference at or below which two images are the same picture."""
    return float(getattr(settings, 'IMAGE_PIXEL_DUPLICATE_MEAN', 3.0))


def review_mean_cutoff() -> float:
    """Mean pixel difference at or below which two images are worth a person's look."""
    return float(getattr(settings, 'IMAGE_PIXEL_REVIEW_MEAN', 8.0))


COMPARE_SIDE = 64          # both images are read at this size, in greyscale
PIXEL_TOLERANCE = 12       # per-pixel difference (0-255) still counted as matching

VERDICT_DUPLICATE = 'duplicate'   # the same picture
VERDICT_REVIEW = 'review'         # close enough that a person should look
VERDICT_DIFFERENT = 'different'   # a lookalike, not a copy


def load_image_matrix(file_path, side=COMPARE_SIDE):
    """A greyscale square of the image as floats, or None when it cannot be read."""
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(file_path) as img:
            img = ImageOps.exif_transpose(img).convert('L').resize((side, side), Image.LANCZOS)
            return np.asarray(img, dtype='float32')
    except Exception as e:  # noqa: BLE001 - comparison is best-effort
        logger.info('Image compare could not read %s: %s', file_path, e)
        return None


def compare_matrices(matrix_a, matrix_b):
    """
    How alike two images are: ``(share_matching, mean_difference)``.

    ``share_matching`` is the fraction of the picture whose brightness agrees
    within PIXEL_TOLERANCE -- a number that can be said out loud ("94% of the
    picture is the same") -- and ``mean_difference`` is what the verdict reads.
    Returns ``(None, None)`` when either image is unreadable.
    """
    if matrix_a is None or matrix_b is None:
        return None, None
    try:
        import numpy as np

        diff = np.abs(matrix_a - matrix_b)
        return float((diff <= PIXEL_TOLERANCE).mean()), float(diff.mean())
    except Exception:  # noqa: BLE001
        return None, None


def pixel_verdict(mean_difference):
    """Turn a mean pixel difference into duplicate / review / different."""
    if mean_difference is None:
        # An unreadable file never proves a copy; let a person decide.
        return VERDICT_REVIEW
    if mean_difference <= duplicate_mean_cutoff():
        return VERDICT_DUPLICATE
    if mean_difference <= review_mean_cutoff():
        return VERDICT_REVIEW
    return VERDICT_DIFFERENT


def compare_image_files(path_a, path_b):
    """``(verdict, share_matching, mean_difference)`` for two image files on disk."""
    share, mean = compare_matrices(load_image_matrix(path_a), load_image_matrix(path_b))
    return pixel_verdict(mean), share, mean


def are_visually_similar(hash_a, hash_b, max_dist=None):
    """True when two hashes are within the duplicate threshold."""
    dist = hamming_distance(hash_a, hash_b)
    if dist is None:
        return False
    cutoff = max_distance() if max_dist is None else int(max_dist)
    return dist <= cutoff

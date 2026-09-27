"""Tests for perceptual image hashing (visual near-duplicate detection)."""
import os
import tempfile

from django.test import TestCase

from PIL import Image, ImageDraw

from ai_processing.image_hash import (
    compute_image_hash,
    hamming_distance,
    visual_similarity,
    are_visually_similar,
    is_image_file,
    HASH_HEX_LEN,
)
from documents.ai_pipeline import merge_visual_matches


def _save(img):
    fd, path = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    img.save(path)
    return path


def _horizontal_gradient(size=256):
    img = Image.new('L', (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            px[x, y] = int(255 * x / (size - 1))
    return img


def _vertical_gradient(size=256):
    img = Image.new('L', (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            px[x, y] = int(255 * y / (size - 1))
    return img


class ImageHashTests(TestCase):
    def setUp(self):
        self._tmp = []

    def tearDown(self):
        for p in self._tmp:
            if os.path.exists(p):
                os.remove(p)

    def _make(self, img):
        path = _save(img)
        self._tmp.append(path)
        return path

    def test_hash_length_and_determinism(self):
        path = self._make(_horizontal_gradient())
        h1 = compute_image_hash(path)
        h2 = compute_image_hash(path)
        self.assertEqual(len(h1), HASH_HEX_LEN)
        self.assertEqual(h1, h2)

    def test_identical_images_are_identical_hash(self):
        base = _horizontal_gradient()
        h1 = compute_image_hash(self._make(base))
        h2 = compute_image_hash(self._make(base.copy()))
        self.assertEqual(hamming_distance(h1, h2), 0)
        self.assertEqual(visual_similarity(h1, h2), 1.0)

    def test_small_drawing_stays_visually_similar(self):
        base = _horizontal_gradient()
        edited = base.copy()
        draw = ImageDraw.Draw(edited)
        draw.rectangle([10, 10, 40, 40], fill=0)  # small scribble in a corner
        h_base = compute_image_hash(self._make(base))
        h_edit = compute_image_hash(self._make(edited))
        self.assertTrue(are_visually_similar(h_base, h_edit),
                        msg=f'distance={hamming_distance(h_base, h_edit)} should be within threshold')

    def test_different_images_are_not_similar(self):
        h_h = compute_image_hash(self._make(_horizontal_gradient()))
        h_v = compute_image_hash(self._make(_vertical_gradient()))
        self.assertFalse(are_visually_similar(h_h, h_v))
        self.assertGreater(hamming_distance(h_h, h_v), 10)

    def test_hamming_distance_guards(self):
        self.assertIsNone(hamming_distance('', 'abcd'))
        self.assertIsNone(hamming_distance('abc', 'abcd'))
        self.assertIsNone(visual_similarity(None, 'abcd'))

    def test_is_image_file(self):
        for ext in ('jpg', 'jpeg', 'png', '.PNG'):
            self.assertTrue(is_image_file(ext))
        for ext in ('pdf', 'docx', 'xlsx', ''):
            self.assertFalse(is_image_file(ext))


class MergeVisualMatchesTests(TestCase):
    def test_tags_existing_text_matches(self):
        existing = [{'id': 1, 'title': 'A', 'similarity': 0.9}]
        merged, changed = merge_visual_matches(existing, [])
        self.assertTrue(changed)
        self.assertEqual(merged[0]['match_type'], 'text')

    def test_appends_new_visual_match_sorted(self):
        existing = [{'id': 1, 'title': 'A', 'similarity': 0.80, 'match_type': 'text'}]
        visual = [{'id': 2, 'title': 'B', 'similarity': 0.95, 'match_type': 'visual'}]
        merged, changed = merge_visual_matches(existing, visual)
        self.assertTrue(changed)
        self.assertEqual([m['id'] for m in merged], [2, 1])  # sorted by similarity desc

    def test_does_not_duplicate_existing_id(self):
        existing = [{'id': 2, 'title': 'B', 'similarity': 0.99, 'match_type': 'text'}]
        visual = [{'id': 2, 'title': 'B', 'similarity': 0.95, 'match_type': 'visual'}]
        merged, changed = merge_visual_matches(existing, visual)
        self.assertEqual(len(merged), 1)
        self.assertFalse(changed)

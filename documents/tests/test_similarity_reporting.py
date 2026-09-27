"""
What "similar" means, and what a percentage on screen is allowed to claim.

Two things were wrong. Images were judged by a 64-bit gradient signature, which
reports bit agreement rather than picture agreement: two tutorial flowcharts
sharing a file-name stem scored "88% similar" with a quarter of the picture
different, while genuine re-exports of one figure scored the same. And the
detail panel rendered the stored ratio with `floatformat:0`, so a text match of
0.9975 printed as "100% match" between two files that are demonstrably not the
same file -- an exact copy cannot even be uploaded.
"""
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from documents.models import Document


def picture(colour=(240, 240, 240), marks=(), size=(96, 96)):
    """A small PNG with optional dark rectangles drawn on it."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', size, colour)
    draw = ImageDraw.Draw(img)
    for box in marks:
        draw.rectangle(box, fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


class PixelComparisonTests(SimpleTestCase):
    """The verdict comes from the pixels, not from the hash."""

    def matrices(self, a, b):
        import io as _io

        from PIL import Image, ImageOps

        import numpy as np

        def load(data):
            with Image.open(_io.BytesIO(data)) as img:
                img = ImageOps.exif_transpose(img).convert('L').resize((64, 64), Image.LANCZOS)
                return np.asarray(img, dtype='float32')
        return load(a), load(b)

    def test_the_same_picture_saved_twice_is_a_duplicate(self):
        from ai_processing.image_hash import VERDICT_DUPLICATE, compare_matrices, pixel_verdict
        marks = [(10, 10, 60, 40)]
        share, mean = compare_matrices(*self.matrices(picture(marks=marks), picture(marks=marks)))
        self.assertEqual(pixel_verdict(mean), VERDICT_DUPLICATE)
        self.assertGreater(share, 0.99)

    def test_two_different_diagrams_are_not_a_duplicate(self):
        from ai_processing.image_hash import VERDICT_DUPLICATE, compare_matrices, pixel_verdict
        a = picture(marks=[(5, 5, 45, 45)])
        b = picture(marks=[(50, 50, 90, 90), (5, 60, 30, 90)])
        share, mean = compare_matrices(*self.matrices(a, b))
        self.assertNotEqual(pixel_verdict(mean), VERDICT_DUPLICATE)
        self.assertLess(share, 0.99)

    def test_an_unreadable_file_never_proves_a_copy(self):
        from ai_processing.image_hash import VERDICT_DUPLICATE, load_image_matrix, pixel_verdict
        self.assertIsNone(load_image_matrix(r'C:\no\such\picture.png'))
        self.assertNotEqual(pixel_verdict(None), VERDICT_DUPLICATE)


class UploadDecisionTests(TestCase):
    """Only a real copy is refused; a lookalike is filed and flagged instead."""

    def setUp(self):
        self.user = User.objects.create_user('dup_head', 'd@example.com', 'Str0ng-Passw0rd!')
        self.user.profile.role = 'qa_staff'
        self.user.profile.save()
        self.client.force_login(self.user)

    def upload(self, name, payload):
        from unittest import mock
        with mock.patch('documents.jobs._dispatch_job_async'):
            return self.client.post(
                reverse('documents:bulk_upload'), {'files': SimpleUploadedFile(name, payload, 'image/png')},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json')

    def test_the_same_picture_again_is_refused(self):
        marks = [(12, 12, 70, 50)]
        self.assertTrue(self.upload('first.png', picture(marks=marks)).json().get('ok'))
        second = self.upload('again.png', picture(marks=marks)).json()
        self.assertFalse(second.get('ok'))
        self.assertTrue(any('same picture' in e.lower() or 'duplicate' in e.lower()
                            for e in second.get('errors', [])), second)

    def test_a_different_diagram_in_the_same_style_is_accepted(self):
        """The old hash-only rule refused these; they are not the same picture."""
        self.assertTrue(self.upload('one.png', picture(marks=[(6, 6, 40, 40)])).json().get('ok'))
        other = self.upload('two.png', picture(marks=[(52, 52, 90, 90), (6, 60, 30, 90)])).json()
        self.assertTrue(other.get('ok'), other)


class SimilarityWordingTests(TestCase):
    """A percentage on screen has to mean something a reader can check."""

    def setUp(self):
        self.doc = Document.objects.create(title='Manuscript v3', file='uploaded_documents/a.docx',
                                           file_type='docx', year=2026, document_type='Report',
                                           content_sha256='a' * 64)
        self.other = Document.objects.create(title='Manuscript v2', file='uploaded_documents/b.docx',
                                             file_type='docx', year=2026, document_type='Report',
                                             content_sha256='b' * 64)

    def describe(self, similarity, match_type='text', same_bytes=False):
        from documents.views import _describe_similarity
        if same_bytes:
            self.other.content_sha256 = self.doc.content_sha256
        return _describe_similarity(self.doc, self.other,
                                    {'similarity': similarity, 'match_type': match_type})

    def test_a_near_identical_text_match_never_claims_to_be_identical(self):
        row = self.describe(0.9975)
        self.assertEqual(round(row['similarity']), 99)
        self.assertFalse(row['identical'])
        self.assertIn('files differ', row['note'])

    def test_a_genuinely_identical_file_says_so(self):
        row = self.describe(1.0, same_bytes=True)
        self.assertTrue(row['identical'])
        self.assertEqual(row['similarity'], 100.0)
        self.assertIn('same file', row['note'].lower())

    def test_the_measure_behind_the_number_is_named(self):
        self.assertIn('wording', self.describe(0.8)['measure'])
        self.assertIn('picture', self.describe(0.8, match_type='visual')['measure'])

    def test_an_image_match_that_needs_a_person_is_labelled_that_way(self):
        row = self.describe(0.85, match_type='visual_review')
        self.assertIn('review', row['match_label'].lower())


class TextAgreementTests(SimpleTestCase):
    """
    What the percentage is measured on.

    The TF-IDF matrix the detector uses is built from `clean_text`, which
    deletes every standalone number. In a generated report the numbers are the
    content, so three "Dashboard Summary" exports reporting 22, 18 and 16
    documents reduced to the same word sequence and scored exactly 1.0000
    against each other -- a literal hundred per cent between files that say
    different things.
    """

    report = ('Dashboard Summary\nGenerated: {date}\nTotal records: 8\n'
              'Metric Value\nTotal documents {total}\nDuplicates to review {dups}\n'
              'Document clusters {clusters}\nAI-processed documents {done}\n')

    def summary(self, date, total, dups, clusters, done):
        return self.report.format(date=date, total=total, dups=dups,
                                  clusters=clusters, done=done)

    def test_the_stripped_text_cannot_tell_two_reports_apart(self):
        """The bug, stated as a test: this is why the old number said 100%."""
        from ai_processing.text_cleaning import clean_text
        one = self.summary('2026-09-07 13:39', 22, 9, 13, 21)
        two = self.summary('2026-06-25 04:51', 18, 6, 6, 17)
        self.assertNotEqual(one, two)
        self.assertEqual(clean_text(one), clean_text(two))

    def test_the_reported_measure_does_tell_them_apart(self):
        from ai_processing.duplicate_checker import text_agreement
        one = self.summary('2026-09-07 13:39', 22, 9, 13, 21)
        two = self.summary('2026-06-25 04:51', 18, 6, 6, 17)
        self.assertLess(text_agreement(one, two), 1.0)

    def test_the_same_text_still_measures_one(self):
        from ai_processing.duplicate_checker import text_agreement
        same = self.summary('2026-09-07 13:39', 22, 9, 13, 21)
        self.assertEqual(round(text_agreement(same, same), 4), 1.0)

    def test_unrelated_text_measures_near_zero(self):
        from ai_processing.duplicate_checker import text_agreement
        self.assertLess(text_agreement('quality assurance accreditation area',
                                       'weekly class schedule for the term'), 0.2)

    def test_empty_text_is_never_a_match(self):
        from ai_processing.duplicate_checker import text_agreement
        self.assertEqual(text_agreement('', 'anything at all'), 0.0)
        self.assertEqual(text_agreement(None, None), 0.0)


class VerifiedMatchTests(TestCase):
    """A candidate the matrix proposes has to survive a second look."""

    def make(self, title, text):
        doc = Document.objects.create(title=title, file=f'uploaded_documents/{title}.docx',
                                      file_type='docx', year=2026, document_type='Report')
        doc.extracted_text = text
        doc.save(update_fields=['extracted_text'])
        return doc

    def setUp(self):
        body = ' '.join(f'section {i} quality assurance evidence' for i in range(60))
        self.doc = self.make('Report A', body + ' total documents 22 duplicates 9')
        self.twin = self.make('Report B', body + ' total documents 22 duplicates 9')
        self.different = self.make('Report C', ' '.join(
            f'class schedule room {i} lecturer assignment' for i in range(60)))

    def candidates(self, docs):
        """What `check_all_duplicates` hands over: positions in the doc list."""
        return [{'index': i, 'similarity': 1.0} for i, _ in enumerate(docs)]

    def test_a_pair_that_really_matches_is_kept(self):
        from documents.ai_pipeline import verified_text_matches
        docs = [self.doc, self.twin]
        kept = verified_text_matches(self.doc, [{'index': 1, 'similarity': 1.0}], docs)
        self.assertEqual([m['id'] for m in kept], [self.twin.pk])
        self.assertEqual(kept[0]['match_type'], 'text')
        self.assertGreater(kept[0]['similarity'], 0.99)

    def test_a_pair_the_matrix_got_wrong_is_dropped(self):
        """The matrix claimed 1.0; the documents share almost no wording."""
        from documents.ai_pipeline import verified_text_matches
        docs = [self.doc, self.different]
        self.assertEqual(verified_text_matches(self.doc, [{'index': 1, 'similarity': 1.0}], docs), [])

    def test_the_number_stored_is_the_one_that_was_verified(self):
        from ai_processing.duplicate_checker import text_agreement
        from documents.ai_pipeline import verified_text_matches
        docs = [self.doc, self.twin]
        kept = verified_text_matches(self.doc, [{'index': 1, 'similarity': 0.42}], docs)
        measured = text_agreement(self.doc.combined_text, self.twin.combined_text)
        self.assertEqual(kept[0]['similarity'], round(measured, 4))

    def test_a_document_is_never_matched_against_itself(self):
        from documents.ai_pipeline import verified_text_matches
        docs = [self.doc, self.twin]
        self.assertEqual(verified_text_matches(self.doc, [{'index': 0, 'similarity': 1.0}], docs), [])

    def test_an_archived_version_is_left_out(self):
        from documents.ai_pipeline import verified_text_matches
        self.twin.is_archived = True
        self.twin.save(update_fields=['is_archived'])
        docs = [self.doc, self.twin]
        self.assertEqual(verified_text_matches(self.doc, [{'index': 1, 'similarity': 1.0}], docs), [])


class SimilarDocumentsPanelTests(TestCase):
    """
    What the reader can tell from the panel.

    Nine drafts of one manuscript share a title that is cut off at the same
    word, so the panel showed five rows that looked like one row repeated, with
    nothing to say which draft each was and no sign that four more matches
    existed.
    """

    TITLE = ('DEVELOPMENT OF AN AI-DRIVEN ONLINE ARCHIVING SYSTEM FOR THE QUALITY '
             'ASSURANCE OFFICE USING ELBOW METHOD AND K-MEANS CLUSTERING ALGORITHM')

    def setUp(self):
        self.uploader = User.objects.create_user('draft_owner', 'o@example.com', 'Str0ng-Passw0rd!')
        self.staff = User.objects.create_user('panel_head', 'p@example.com', 'Str0ng-Passw0rd!')
        self.staff.profile.role = 'qa_staff'
        self.staff.profile.save()

        def draft(n):
            return Document.objects.create(
                title=self.TITLE, file=f'uploaded_documents/draft{n}.docx', file_type='docx',
                year=2026, document_type='Report', uploaded_by=self.uploader)

        self.drafts = [draft(n) for n in range(9)]
        self.doc = Document.objects.create(
            title=self.TITLE, file='uploaded_documents/current.docx', file_type='docx',
            year=2026, document_type='Report', duplicate_status='possible',
            similar_documents=[{'id': d.pk, 'title': self.TITLE, 'similarity': 0.99 - i * 0.005,
                                'match_type': 'text'} for i, d in enumerate(self.drafts)])
        self.client.force_login(self.staff)

    def panel(self):
        return self.client.get(
            reverse('documents:detail', args=[self.doc.pk]) + '?panel=1').content.decode()

    def test_the_panel_says_how_many_matches_there_are(self):
        self.assertIn('Closest 5 of 9', self.panel())

    def test_no_count_is_shown_when_nothing_was_cut(self):
        self.doc.similar_documents = self.doc.similar_documents[:3]
        self.doc.save(update_fields=['similar_documents'])
        self.assertNotIn('Closest', self.panel())

    def test_each_row_identifies_the_document_it_points_at(self):
        """
        Title, badge, percentage, date and uploader are all the same on these
        rows -- nine drafts uploaded in one batch by one person. The file name
        is the only thing that differs, so it is the thing that has to show.
        """
        html = self.panel()
        for n in range(5):
            self.assertIn(f'draft{n}.docx', html)
        self.assertIn('draft_owner', html)

    def test_a_match_staff_already_ruled_on_says_so(self):
        matches = self.doc.similar_documents
        matches[0]['review'] = 'dismissed'
        matches[1]['review'] = 'confirmed'
        self.doc.similar_documents = matches
        self.doc.save(update_fields=['similar_documents'])
        html = self.panel()
        self.assertIn('Reviewed: not a duplicate.', html)
        self.assertIn('Reviewed: confirmed as a duplicate.', html)

    def test_an_open_match_makes_no_claim_about_a_decision(self):
        self.assertNotIn('Reviewed:', self.panel())

    def test_a_strong_match_is_not_called_merely_related(self):
        """0.96 used to read "Related content", which understates a shared draft."""
        from documents.views import _describe_similarity
        row = _describe_similarity(self.doc, self.drafts[0], {'similarity': 0.96})
        self.assertIn('another draft', row['note'])
        self.assertNotIn('Related content', row['note'])

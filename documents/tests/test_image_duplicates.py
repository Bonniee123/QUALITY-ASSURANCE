"""
Duplicate detection for images.

Images were being judged by cosine similarity over their OCR text. A diagram
OCRs to a dozen words -- "The system", "uploads document", a few box labels --
and two unrelated flowcharts sharing that vocabulary scored 1.000 against each
other, so both were sent for review. The pixels, which are the actual content
of an image, were only ever consulted afterwards and could add a flag but never
remove a wrong one.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from ai_processing.image_hash import are_visually_similar, hamming_distance
from documents.models import Document


def make_doc(**kwargs):
    defaults = dict(
        title='Doc', file='uploaded_documents/2026/01/x.pdf', file_type='pdf',
        year=2026, document_type='Report',
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


class ImageTextVerdictTests(TestCase):
    """An image's OCR text must not decide whether it is a duplicate."""

    def test_two_different_diagrams_sharing_ocr_words_are_not_flagged(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        # Short, overlapping OCR of the kind two unrelated flowcharts produce.
        shared = 'The system user uploads document process start end decision'
        make_doc(title='Flowchart', file='uploaded_documents/a.png', file_type='png',
                 extracted_text=shared + ' browse vehicles',
                 image_phash='0000000000000000')
        make_doc(title='Bookings', file='uploaded_documents/b.png', file_type='png',
                 extracted_text=shared + ' booking list',
                 # Far away in pixel terms: a different picture.
                 image_phash='ffffffffffffffff')

        run_full_ai_pipeline(None)

        for doc in Document.objects.all():
            self.assertEqual(
                doc.duplicate_status, 'none',
                f'{doc.title} was flagged on OCR text despite being a different image',
            )

    def test_visually_identical_images_are_still_flagged(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Figure 2', file='uploaded_documents/f2.png', file_type='png',
                 extracted_text='architecture diagram', image_phash='abcdef0123456789')
        make_doc(title='Figure 2 copy', file='uploaded_documents/f2b.png', file_type='png',
                 extracted_text='completely different words here', image_phash='abcdef0123456789')

        run_full_ai_pipeline(None)

        statuses = list(Document.objects.values_list('duplicate_status', flat=True))
        self.assertEqual(statuses, ['possible', 'possible'],
                         'identical pixels must still be caught')

    def test_a_flagged_image_records_that_it_matched_visually(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='A', file='uploaded_documents/a.png', file_type='png',
                 extracted_text='one', image_phash='1111222233334444')
        make_doc(title='B', file='uploaded_documents/b.png', file_type='png',
                 extracted_text='two', image_phash='1111222233334444')
        run_full_ai_pipeline(None)

        doc = Document.objects.filter(duplicate_status='possible').first()
        self.assertIsNotNone(doc)
        kinds = {m.get('match_type') for m in (doc.similar_documents or [])}
        self.assertEqual(kinds, {'visual'})


class ShortTextVerdictTests(TestCase):
    """The same guard protects any document too short to characterise."""

    def test_two_short_documents_are_not_flagged_on_text_alone(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Memo A', extracted_text='Approved by the committee. Signed.')
        make_doc(title='Memo B', extracted_text='Approved by the committee. Signed.')

        run_full_ai_pipeline(None)

        self.assertEqual(
            set(Document.objects.values_list('duplicate_status', flat=True)), {'none'},
            'documents below the minimum text length must not be flagged on cosine similarity',
        )

    def test_long_duplicate_documents_are_still_flagged(self):
        """The guard must not blunt detection where the text really is the document."""
        from documents.ai_pipeline import run_full_ai_pipeline

        body = ('The quality assurance office maintains records of every accreditation '
                'area including faculty credentials research output and extension work. ') * 12
        make_doc(title='Report', extracted_text=body)
        make_doc(title='Report copy', extracted_text=body)

        run_full_ai_pipeline(None)

        self.assertEqual(set(Document.objects.values_list('duplicate_status', flat=True)),
                         {'possible'}, 'a real text duplicate must still be caught')


class PerceptualCutoffTests(TestCase):
    """
    The distance under which two images count as the same.

    Ten was loose enough to pair unrelated line diagrams, which are mostly white
    with thin strokes and therefore hash alike. Measured over the archive, every
    pair at distance 4 or less was the same figure re-uploaded and the false
    pairs began at 6.
    """

    def test_near_identical_images_are_similar(self):
        # One bit apart: the same picture, re-encoded.
        self.assertEqual(hamming_distance('0000000000000000', '0000000000000001'), 1)
        self.assertTrue(are_visually_similar('0000000000000000', '0000000000000001'))

    def test_diagrams_nine_bits_apart_are_not_called_the_same(self):
        # This is the FLOWCHART.png / bookings.png case from the archive.
        a, b = '0000000000000000', '00000000000001ff'
        self.assertEqual(hamming_distance(a, b), 9)
        self.assertFalse(are_visually_similar(a, b),
                         'nine bits apart is a different picture, not a duplicate')

    @override_settings(IMAGE_PHASH_MAX_DISTANCE=10)
    def test_the_cutoff_is_configurable(self):
        a, b = '0000000000000000', '00000000000001ff'
        self.assertTrue(are_visually_similar(a, b),
                        'the threshold must remain tunable per deployment')


class ImageOnlyCorpusTests(TestCase):
    """
    An archive with no usable text must still be processed.

    `compute_tfidf_keywords` fails outright when there are too few terms to
    vectorise -- "after pruning, no terms remain" -- which a set of diagrams and
    screenshots reaches easily. The pipeline used to return at that point, so an
    image-heavy corpus got no duplicate detection of any kind and every document
    stayed on 'pending_check', showing as "Checking…" for ever.
    """

    def test_nothing_is_left_pending_when_there_is_no_usable_text(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        for i in range(3):
            make_doc(title=f'Screenshot {i}', file=f'uploaded_documents/s{i}.png',
                     file_type='png', extracted_text='', duplicate_status='pending_check',
                     image_phash=f'{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}')

        run_full_ai_pipeline(None)

        self.assertFalse(Document.objects.filter(duplicate_status='pending_check').exists(),
                         'an image-only corpus was left on "Checking…"')

    def test_identical_images_are_still_caught_without_any_text(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Chart', file='uploaded_documents/c1.png', file_type='png',
                 extracted_text='', duplicate_status='pending_check',
                 image_phash='aaaabbbbccccdddd')
        make_doc(title='Chart again', file='uploaded_documents/c2.png', file_type='png',
                 extracted_text='', duplicate_status='pending_check',
                 image_phash='aaaabbbbccccdddd')

        run_full_ai_pipeline(None)

        self.assertEqual(Document.objects.filter(duplicate_status='possible').count(), 2,
                         'pixel comparison must work with no text at all')

    def test_the_result_says_what_it_did(self):
        # Two documents: a single one exits earlier still, on "need 2+ documents
        # for clustering", before text vectorisation is even attempted.
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='One', file='uploaded_documents/o.png', file_type='png',
                 extracted_text='', image_phash='0f0f0f0f0f0f0f0f')
        make_doc(title='Two', file='uploaded_documents/t.png', file_type='png',
                 extracted_text='', image_phash='f0f0f0f0f0f0f0f0')

        result = run_full_ai_pipeline(None)

        self.assertIn('image', result.lower(),
                      'the message must say text was unusable and images were compared instead')


class CorroboratedVisualMatchTests(TestCase):
    """
    The band where pixels alone cannot decide.

    Between the conclusive distance and the wider review distance, a figure
    re-exported at another size looks exactly as similar as a different diagram
    drawn in the same style -- figure3 and figure3_3 sat at the same distance as
    figure5-system-architecture and figure6-deployment-diagram. The file name
    settles it: same stem, same figure.
    """

    # Nine bits apart: inside the review band, outside the conclusive one.
    NEAR_A = '0000000000000000'
    NEAR_B = '00000000000001ff'

    def test_same_figure_re_exported_is_flagged(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Figure 3', file='uploaded_documents/figure3-use-case-diagram.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_A)
        make_doc(title='Figure 3 again', file='uploaded_documents/figure3-use-case-diagram_3.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_B)

        run_full_ai_pipeline(None)

        self.assertEqual(Document.objects.filter(duplicate_status='possible').count(), 2,
                         'the same figure saved twice must be flagged')

    def test_different_diagrams_at_the_same_distance_are_not_flagged(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='Architecture', file='uploaded_documents/figure5-system-architecture.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_A)
        make_doc(title='Deployment', file='uploaded_documents/figure6-deployment-diagram.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_B)

        run_full_ai_pipeline(None)

        self.assertEqual(set(Document.objects.values_list('duplicate_status', flat=True)), {'none'},
                         'two different diagrams must not be paired on appearance alone')

    def test_a_corroborated_match_says_so(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='F2', file='uploaded_documents/figure2-flowchart.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_A)
        make_doc(title='F2 copy', file='uploaded_documents/figure2-flowchart_1.png',
                 file_type='png', extracted_text='', image_phash=self.NEAR_B)
        run_full_ai_pipeline(None)

        doc = Document.objects.filter(duplicate_status='possible').first()
        kinds = {m.get('match_type') for m in (doc.similar_documents or [])}
        self.assertEqual(kinds, {'visual_named'},
                         'a name-corroborated match must be distinguishable from a pixel-certain one')

    def test_matching_names_do_not_rescue_visually_unrelated_images(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        # Same stem, but far apart in pixels: a name alone is not evidence.
        make_doc(title='A', file='uploaded_documents/figure9-chart.png', file_type='png',
                 extracted_text='', image_phash='0000000000000000')
        make_doc(title='B', file='uploaded_documents/figure9-chart_1.png', file_type='png',
                 extracted_text='', image_phash='ffffffffffffffff')

        run_full_ai_pipeline(None)

        self.assertEqual(set(Document.objects.values_list('duplicate_status', flat=True)), {'none'},
                         'the name only corroborates a close visual match, it cannot create one')

    def test_a_conclusive_pixel_match_needs_no_name_agreement(self):
        from documents.ai_pipeline import run_full_ai_pipeline

        make_doc(title='One', file='uploaded_documents/screenshot-alpha.png', file_type='png',
                 extracted_text='', image_phash='1234567890abcdef')
        make_doc(title='Two', file='uploaded_documents/totally-different-name.png',
                 file_type='png', extracted_text='', image_phash='1234567890abcdef')

        run_full_ai_pipeline(None)

        self.assertEqual(Document.objects.filter(duplicate_status='possible').count(), 2,
                         'identical pixels are conclusive whatever the files are called')


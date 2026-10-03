"""
What a refused near-duplicate upload tells the person who uploaded it.

The message used to say only that something had been detected. It never said
the file had been discarded, it cut the matched title mid-word at sixty
characters, and it threw away the similarity it had just measured. These tests
hold the replacement wording in place, and keep the two duplicate outcomes --
blocked outright, and stored for review -- describing themselves differently.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from documents.models import Document
from documents.near_duplicates import (
    as_percent,
    blocked_message,
    document_label,
    short_title,
)
from documents.views import matched_document_label


class ShortTitleTests(TestCase):
    def test_a_short_title_is_left_alone(self):
        self.assertEqual(short_title('Area VII Report'), 'Area VII Report')

    def test_a_long_title_is_cut_at_a_word_boundary(self):
        title = 'DEVELOPMENT OF AN ONLINE ARCHIVING SYSTEM FOR THE QUALITY ASSURANCE OFFICE'
        cut = short_title(title)
        self.assertTrue(cut.endswith('…'))
        self.assertLessEqual(len(cut), 49)
        # the defect: the old cut landed mid-phrase and left the gap inside the
        # quotation marks, as 'FOR THE "'
        self.assertFalse(cut[:-1].endswith(' '))
        self.assertTrue(title.startswith(cut[:-1]))
        self.assertIn(cut[:-1].split()[-1], title.split())

    def test_whitespace_is_normalised(self):
        self.assertEqual(short_title('  Area   VII \n Report '), 'Area VII Report')

    def test_an_empty_title_survives(self):
        self.assertEqual(short_title(''), '')
        self.assertEqual(short_title(None), '')


class LabelAndMessageTests(TestCase):
    def test_a_label_is_quoted(self):
        self.assertEqual(document_label('Area VII Report'), '“Area VII Report”')

    def test_a_missing_title_falls_back_to_a_description(self):
        self.assertEqual(document_label(''), 'a document already in the archive')

    def test_the_message_leads_with_the_outcome(self):
        message = blocked_message('“Area VII Report”', 98)
        self.assertTrue(message.startswith('Not uploaded'))
        self.assertIn('98%', message)
        self.assertIn('already in the archive', message)
        # the wording that said nothing about what happened
        self.assertNotIn('detected', message.lower())

    def test_percentages_are_whole_numbers(self):
        self.assertEqual(as_percent(0.9712), 97)
        self.assertEqual(as_percent(1.0), 100)
        self.assertEqual(as_percent(None), 0)
        self.assertEqual(as_percent('not a number'), 0)


class MatchedDocumentLabelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('dupadmin', 'a@example.com', 'pw')
        self.doc = Document.objects.create(
            title='DEVELOPMENT OF AN ONLINE ARCHIVING SYSTEM FOR THE QUALITY ASSURANCE OFFICE',
            file_type='docx',
            year=2026,
            uploaded_by=self.admin,
        )

    def test_a_reader_who_may_open_the_match_sees_a_tidy_title(self):
        label = matched_document_label(self.admin, self.doc)
        self.assertTrue(label.startswith('“'))
        self.assertTrue(label.endswith('”'))
        self.assertIn('…', label)
        self.assertNotIn(' ”', label)

    def test_no_document_means_no_title(self):
        self.assertEqual(matched_document_label(self.admin, None),
                         'a document already in the archive')

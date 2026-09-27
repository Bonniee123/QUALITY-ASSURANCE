from django.test import SimpleTestCase

from documents.auto_metadata import build_description, extract_metadata_from_text


class BuildDescriptionTests(SimpleTestCase):
    def test_uses_abstract_section(self):
        text = (
            "DEVELOPMENT OF AN AI SYSTEM\n\n"
            "Abstract\n"
            "This study presents an AI-driven online archiving platform for the QA office. "
            "It automates document classification and evidence mapping for accreditation reviews."
        )
        desc = build_description(text, title='Development Of An Ai System', document_type='Research')
        self.assertIn('AI-driven online archiving', desc)
        self.assertNotIn('DEVELOPMENT OF AN AI SYSTEM', desc)

    def test_skips_junk_opening_lines(self):
        text = (
            "1\n"
            "Page 1\n"
            "UNIVERSITY OF EXAMPLE\n\n"
            "Introduction\n"
            "Quality assurance requires organized evidence collection across departments each year."
        )
        desc = build_description(text, title='QA Manual', document_type='Manual')
        self.assertIn('Quality assurance requires', desc)

    def test_fallback_when_text_is_thin(self):
        desc = build_description('', title='Annual Report', document_type='Report', filename='annual_report_2025.pdf')
        self.assertEqual(desc, 'Report — Annual Report.')

    def test_extract_metadata_sets_description(self):
        text = (
            "Policy Title\n\n"
            "Overview\n"
            "This policy defines standards for document retention and audit preparation in the QA office."
        )
        meta = extract_metadata_from_text(text, filename='retention_policy.pdf')
        self.assertIn('document retention', meta['description'])


class DocumentTypeKeywordTests(SimpleTestCase):
    """
    The type keywords are whole words.

    They used to be searched as bare fragments, so every text containing
    "conform", "information" or "performance" carried the word "form" inside it:
    an ISO certificate of registration was filed as a Form, and so were meeting
    minutes that mentioned performance data.
    """

    def guess(self, text, filename='document.pdf'):
        return extract_metadata_from_text(text, filename=filename)['document_type']

    def test_a_word_hidden_inside_another_word_no_longer_counts(self):
        self.assertEqual(self.guess(
            'This certificate records that the management system was found to conform '
            'to the requirements of the standard.', filename='registration.pdf'), 'Certificate')
        self.assertEqual(self.guess(
            'Minutes of the management review meeting. The committee examined performance '
            'data and the information it is drawn from.', filename='review.pdf'), 'Minutes')

    def test_the_word_itself_still_counts(self):
        self.assertEqual(self.guess(
            'Corrective Action Request Form. Complete this form and return it to the office.',
            filename='request.pdf'), 'Form')

    def test_a_plural_still_counts(self):
        self.assertEqual(self.guess(
            'The office reports quarterly to the board on its collections.',
            filename='quarterly.pdf'), 'Report')

    def test_a_file_name_separator_does_not_hide_the_word(self):
        self.assertEqual(self.guess('', filename='annual_report_2025.pdf'), 'Report')
        self.assertEqual(self.guess('', filename='faculty-manual-v3.pdf'), 'Manual')

    def test_text_with_no_keyword_stays_the_plain_default(self):
        self.assertEqual(self.guess(
            'The register lists the risks identified during the review and who is accountable '
            'for each one.', filename='register.pdf'), 'Document')


class LetterheadTitleTests(SimpleTestCase):
    """
    A letterheaded document's title is not its first line.

    Four unrelated documents -- a survey questionnaire, a data-gathering tool and
    two request letters -- were all archived as "Republic of the Philippines",
    because that is what every one of them says on line one. In the repository
    they then looked like copies of each other while sitting in different
    clusters, which was correct for their content but read as a clustering fault.
    """

    LETTERHEAD = (
        'Republic of the Philippines\n'
        'NORTH EASTERN MINDANAO STATE UNIVERSITY\n'
        'Poblacion, Cagwait, Surigao del Sur 8304\n'
        'www.nemsu.edu.ph\n'
    )

    def test_title_is_taken_from_past_the_letterhead(self):
        from documents.auto_metadata import _title_from_text
        self.assertEqual(
            _title_from_text(self.LETTERHEAD + 'SURVEY QUESTIONNAIRE\nName: ______'),
            'SURVEY QUESTIONNAIRE',
        )

    def test_two_documents_behind_the_same_letterhead_get_different_titles(self):
        from documents.auto_metadata import _title_from_text
        first = _title_from_text(self.LETTERHEAD + 'SURVEY QUESTIONNAIRE\nbody')
        second = _title_from_text(self.LETTERHEAD + 'Faculty Development Plan\nbody')
        self.assertNotEqual(first, second)

    def test_a_real_title_mentioning_a_university_is_kept(self):
        from documents.auto_metadata import _looks_like_letterhead
        self.assertFalse(_looks_like_letterhead('University Library Annual Report 2026'))

    def test_masthead_lines_are_recognised(self):
        from documents.auto_metadata import _looks_like_letterhead
        for line in (
            'Republic of the Philippines',
            'NORTH EASTERN MINDANAO STATE UNIVERSITY',
            'Poblacion, Cagwait, Surigao del Sur 8304',
            'www.nemsu.edu.ph',
            'registrar@nemsu.edu.ph',
        ):
            self.assertTrue(_looks_like_letterhead(line), msg=line)

    def test_ordinary_titles_are_never_rejected(self):
        from documents.auto_metadata import _looks_like_letterhead
        for line in (
            'SURVEY QUESTIONNAIRE',
            'Faculty Development Plan',
            'Annual Report 2026',
            'Minutes of the Meeting',
            'Evaluation of www.example.com as a learning platform',
        ):
            self.assertFalse(_looks_like_letterhead(line), msg=line)

    def test_all_letterhead_falls_back_to_the_filename_title(self):
        from documents.auto_metadata import _title_from_text
        # Nothing but masthead: returning '' leaves the filename-derived default.
        self.assertEqual(_title_from_text(self.LETTERHEAD), '')

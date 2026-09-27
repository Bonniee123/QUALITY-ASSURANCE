"""
Auto-metadata files a staff upload under the configured area it is about.

The map was keyed to its own list of area names, which ran one place behind the
configured areas from Area IV on ("Area IV - Research" while Area V is Research),
stored that string instead of the area, and let the first subject mentioned win:
a research agenda that mentioned "faculty research" went to Area II, and so did a
laboratory manual that mentioned "faculty" once. Documents filed that way were
invisible to the Faculty of the right area.
"""
from django.test import SimpleTestCase, TestCase

from documents.auto_metadata import _years_in_name, detect_area_code, extract_metadata_from_text
from qa_structure.models import AccreditationArea

AREAS = [('Area I', 'Vision, Mission, Goals and Objectives'), ('Area II', 'Faculty'),
         ('Area III', 'Curriculum and Instruction'), ('Area IV', 'Support to Students'), ('Area V', 'Research'),
         ('Area VI', 'Extension and Community Involvement'), ('Area VII', 'Library'),
         ('Area VIII', 'Physical Plant and Facilities'), ('Area IX', 'Laboratories'), ('Area X', 'Administration')]


class AreaDetectionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        for code, name in AREAS:
            AccreditationArea.objects.update_or_create(area_code=code, defaults={'area_name': name})

    def test_research_goes_to_the_configured_research_area(self):
        text = ('Research agenda of the institution. The research office funds faculty research projects, thesis '
                'advising, journal publication incentives and research ethics review.').lower()
        self.assertEqual(detect_area_code(text), 'Area V')

    def test_one_mention_of_faculty_does_not_decide(self):
        text = ('Laboratory safety manual. Chemical storage, fume hood inspection and glassware handling are '
                'described for every science laboratory. The faculty adviser signs the monthly laboratory '
                'checklist.').lower()
        self.assertEqual(detect_area_code(text), 'Area IX')

    def test_an_explicit_area_reference_wins(self):
        self.assertEqual(detect_area_code('evidence for area 5 of the survey visit, faculty faculty faculty'), 'Area V')
        self.assertEqual(detect_area_code('submitted under area vii: library holdings'), 'Area VII')

    def test_a_single_passing_mention_assigns_nothing(self):
        self.assertEqual(detect_area_code('minutes of the meeting; the library was mentioned once'), '')

    def test_names_follow_the_configured_table(self):
        AccreditationArea.objects.filter(area_code='Area V').update(area_name='Research, Development and Innovation')
        self.assertEqual(detect_area_code('research research thesis'), 'Area V')

    def test_metadata_carries_the_code_not_a_label(self):
        meta = extract_metadata_from_text('Library acquisitions report. The library added periodicals and the '
                                          'librarian updated the circulation desk hours.', 'library_report.docx')
        self.assertEqual(meta['qa_area'], 'Area VII')

    def test_an_area_named_in_a_file_name_with_underscores(self):
        """Underscores join words, so "Area_VII" read as neither "area vii" nor anything."""
        holdings = 'Title\tCall Number\tCopies\nDatabase Systems\tQA76.9\t5'
        self.assertEqual(extract_metadata_from_text(holdings, 'Area_VII_Holdings.xlsx')['qa_area'], 'Area VII')
        self.assertEqual(extract_metadata_from_text(holdings, 'area-7-holdings.xlsx')['qa_area'], 'Area VII')

    def test_a_subject_in_a_file_name_with_underscores(self):
        text = 'Inventory of holdings. Title, call number and copies for each library title.'
        self.assertEqual(extract_metadata_from_text(text, 'Library_Holdings_2025.xlsx')['qa_area'], 'Area VII')


class SpreadsheetTitleTests(SimpleTestCase):

    def test_a_spreadsheet_is_titled_by_its_file_name_not_its_column_headings(self):
        text = 'Research Title Author Year Status\nMachine learning study Dela Cruz 2024 Published'
        meta = extract_metadata_from_text(text, 'Area_V_Research_Agenda_and_Output.xlsx')
        self.assertEqual(meta['title'], 'Area V Research Agenda And Output')

    def test_other_documents_still_take_their_title_from_the_text(self):
        meta = extract_metadata_from_text('Faculty Development Plan\nbody text here', 'scan_0042.pdf')
        self.assertEqual(meta['title'], 'Faculty Development Plan')


class YearTests(SimpleTestCase):

    def test_a_year_in_a_file_name_with_underscores(self):
        self.assertEqual(_years_in_name('QATEST_Report_2023.docx'), ['2023'])
        meta = extract_metadata_from_text('Annual report without a school year line. ' * 3, 'QATEST_Report_2023.docx')
        self.assertEqual(meta['year'], '2023')

    def test_years_after_2029_are_recognised(self):
        meta = extract_metadata_from_text('Development plan for the year 2031 covering campus expansion.', 'plan.docx')
        self.assertEqual(meta['year'], '2031')
        meta = extract_metadata_from_text('School Year 2030-2031 accomplishment report.', 'report.docx')
        self.assertEqual(meta['year'], '2030')

    def test_digits_inside_a_longer_number_are_not_a_year(self):
        self.assertEqual(_years_in_name('scan_120234.pdf'), [])


class SpreadsheetDescriptionTests(TestCase):

    TEXT = ('Title File Type Year Document Type Cluster Acc Area Uploaded At\n'
            'Research 19 DOCX 2026 Research 19 Area II 2026-09-20\n'
            'Plan 4 PDF 2025 Plan 3 Area I 2026-09-21')

    def test_a_spreadsheet_is_described_by_title_and_size_not_its_headings(self):
        meta = extract_metadata_from_text(self.TEXT, 'inventory_report_20260921_1810.xlsx')
        self.assertEqual(meta['description'], 'Spreadsheet — Inventory Report 20260921 1810, 3 rows.')

    def test_existing_spreadsheets_can_be_refreshed_alone(self):
        from io import StringIO
        from django.core.management import call_command
        from documents.models import Document
        sheet = Document.objects.create(title='Document Inventory Report', file='uploaded_documents/inv.xlsx',
                                        file_type='xlsx', year=2026, extracted_text=self.TEXT,
                                        description='Title File Type Year Document Type Cluster')
        edited = Document.objects.create(title='Plan', file='uploaded_documents/plan.pdf', file_type='pdf',
                                         year=2026, extracted_text='Plan text. ' * 10,
                                         description='Hand-written description.')
        call_command('refresh_descriptions', '--spreadsheets-only', stdout=StringIO())
        sheet.refresh_from_db(); edited.refresh_from_db()
        self.assertEqual(sheet.description, 'Spreadsheet — Document Inventory Report, 3 rows.')
        self.assertEqual(edited.description, 'Hand-written description.')

    def test_a_title_that_is_the_heading_row_is_replaced_but_a_typed_one_is_kept(self):
        from io import StringIO
        from django.core.management import call_command
        from documents.models import Document
        auto = Document.objects.create(title='Title File Type Year Document Type Cluster Acc Area Uploaded At',
                                       file='uploaded_documents/Library_Holdings_2025.xlsx', file_type='xlsx',
                                       year=2025, extracted_text=self.TEXT)
        typed = Document.objects.create(title='Title', file='uploaded_documents/other.xlsx', file_type='xlsx',
                                        year=2025, extracted_text=self.TEXT)
        call_command('refresh_descriptions', '--spreadsheets-only', stdout=StringIO())
        auto.refresh_from_db(); typed.refresh_from_db()
        self.assertEqual(auto.title, 'Library Holdings 2025')
        self.assertEqual(auto.description, 'Spreadsheet — Library Holdings 2025, 3 rows.')
        self.assertEqual(typed.title, 'Title')

    def test_area_numerals_stay_capitals_in_a_title_from_a_file_name(self):
        meta = extract_metadata_from_text(self.TEXT, 'Area_VII_Library_Holdings_Inventory.xlsx')
        self.assertEqual(meta['title'], 'Area VII Library Holdings Inventory')
        self.assertEqual(extract_metadata_from_text('', 'area_iv_student_handbook.pdf')['title'],
                         'Area IV Student Handbook')

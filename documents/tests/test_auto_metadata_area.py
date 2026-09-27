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

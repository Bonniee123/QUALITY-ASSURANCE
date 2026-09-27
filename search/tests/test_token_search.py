"""
Search matches the words of a query, not one unbroken phrase.

Measured on a copy of the live data before the change (S-SR-01, S-AR-03, Q1-Q8):

* "policy enrollment" found nothing for a document about an "enrollment policy";
  a phrase broken across two lines was missed; "policies" missed "policy".
* "0.4" matched documents through the TF-IDF scores stored beside each keyword,
  and a lone '"' matched every document through the JSON punctuation.
* The area filter "Area I" also returned Areas II, III, IV and IX.
* The Repository re-sorted every search by upload date, so a title match could
  sit below pages of passing mentions.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea
from search.search_service import query_terms, search_documents


def make_doc(title, text='', **extra):
    fields = dict(title=title, file=f'uploaded_documents/{title[:20]}.pdf', file_type='pdf', year=2026,
                  document_type='Evidence', extracted_text=text)
    fields.update(extra)
    return Document.objects.create(**fields)


def titles(qs):
    return sorted(d.title for d in qs)


class WordMatchingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        make_doc('Enrollment Policy', 'The enrollment policy of the university covers admission and '
                                      'transfer.\nStudent records are kept by the registrar.')
        make_doc('Library Report', 'Library holdings and periodicals were counted in June.',
                 tfidf_keywords=[['library', 0.4123], ['holdings', 0.2]])
        make_doc('Budget Memo', 'The committee approved a 0.4 percent increase for supplies.')
        make_doc('Grading Policies', 'Policies on grading and class standing.')

    def test_words_in_any_order(self):
        self.assertEqual(titles(search_documents('policy enrollment')), ['Enrollment Policy'])

    def test_words_across_a_line_break(self):
        self.assertEqual(titles(search_documents('transfer student records')), ['Enrollment Policy'])

    def test_plural_and_singular_find_each_other(self):
        self.assertEqual(titles(search_documents('policies')), ['Enrollment Policy', 'Grading Policies'])
        self.assertEqual(titles(search_documents('policy')), ['Enrollment Policy', 'Grading Policies'])
        self.assertEqual(titles(search_documents('reports')), ['Library Report'])

    def test_case_extra_spaces_and_partial_words(self):
        self.assertEqual(titles(search_documents('  ENROLL   polic ')), ['Enrollment Policy'])

    def test_every_word_must_appear(self):
        self.assertEqual(titles(search_documents('enrollment library')), [])

    def test_numbers_do_not_match_keyword_scores(self):
        # "0.4" is in the Library Report's stored keyword scores, not in its text.
        self.assertEqual(titles(search_documents('0.4')), ['Budget Memo'])

    def test_keyword_terms_still_match(self):
        Document.objects.filter(title='Library Report').update(extracted_text='')
        self.assertEqual(titles(search_documents('holdings')), ['Library Report'])

    def test_punctuation_is_taken_literally(self):
        self.assertEqual(titles(search_documents('"')), [])
        self.assertEqual(titles(search_documents("' OR 1=1")), [])
        self.assertEqual(titles(search_documents('<script>')), [])
        self.assertEqual(titles(search_documents('100%')), [])

    def test_sentence_punctuation_is_not_part_of_the_word(self):
        self.assertEqual(titles(search_documents('"enrollment policy,"')), ['Enrollment Policy'])

    def test_query_terms(self):
        self.assertEqual(query_terms('Policies  (reports)'), [['policies', 'policy'], ['reports', 'report']])


class AreaFilterTests(TestCase):

    def test_area_i_is_only_area_i(self):
        codes = ['Area I', 'Area II', 'Area III', 'Area IV', 'Area IX']
        for code in codes:
            area, _ = AccreditationArea.objects.get_or_create(area_code=code, defaults={'area_name': code})
            make_doc(f'Evidence for {code}', acc_area=area, qa_area=code)
        self.assertEqual(titles(search_documents('', {'qa_area': 'Area I'})), ['Evidence for Area I'])


@override_settings(ENABLE_HYBRID_SMART_SEARCH=True)
class RepositoryOrderTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user('order_admin', password='pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        self.client.force_login(self.admin)
        self.title_match = make_doc('Research Agenda 2026', 'Priorities for the coming years.')
        for i in range(3):  # newer documents that only mention it in passing
            make_doc(f'Minutes {i}', 'Item 4: the research agenda was noted.')

    def rows(self, **params):
        html = self.client.get(reverse('documents:repository'), params).content.decode()
        return [line for line in html.split('data-doc-id="')[1:]]

    def test_a_search_lists_the_best_match_first(self):
        first = self.rows(q='research agenda')[0]
        self.assertTrue(first.startswith(f'{self.title_match.pk}"'))

    def test_a_chosen_column_sort_still_wins(self):
        first = self.rows(q='research agenda', sort='uploaded', dir='desc')[0]
        self.assertFalse(first.startswith(f'{self.title_match.pk}"'))

    def test_without_a_search_the_newest_come_first(self):
        first = self.rows()[0]
        newest = Document.objects.order_by('-uploaded_at', '-id').first()
        self.assertTrue(first.startswith(f'{newest.pk}"'))

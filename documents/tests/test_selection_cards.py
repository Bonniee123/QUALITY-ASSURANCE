"""
The two selection grids: Area Submissions and Document Clusters.

Both draw the same card, and on both the card was too narrow to say what it
was. Measured at 1440px, the track produced a 155px card carrying a single
nowrap line: 4 of the 10 area names were clipped mid-word, and all 32 cluster
labels were. Every cluster label opens with the facets it was grouped on
(area, document type) and 21 of the 32 opened with the same three words, so
the part that identified the cluster was always the part cut off.

Two ordering faults came with it. The areas were ordered by their code as text,
which put "Area IX" between "Area IV" and "Area V", and the clusters were
ordered by the index K-Means happened to assign, which scattered the fourteen
single-document groups ahead of the nine-document one.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from documents.models import ClusterResult, Document
from documents.views import area_sort_key, split_cluster_label
from qa_structure.models import AccreditationArea

SEP = '·'


class AreaOrderingTests(SimpleTestCase):

    def test_roman_numerals_are_read_as_numbers(self):
        codes = ['Area I', 'Area II', 'Area III', 'Area IV', 'Area IX',
                 'Area V', 'Area VI', 'Area VII', 'Area VIII', 'Area X']
        self.assertEqual(
            sorted(codes, key=area_sort_key),
            ['Area I', 'Area II', 'Area III', 'Area IV', 'Area V',
             'Area VI', 'Area VII', 'Area VIII', 'Area IX', 'Area X'])

    def test_the_ninth_area_no_longer_sits_fifth(self):
        self.assertGreater(area_sort_key('Area IX'), area_sort_key('Area VIII'))
        self.assertLess(area_sort_key('Area IX'), area_sort_key('Area X'))

    def test_a_code_without_a_numeral_sorts_after_the_numbered_ones(self):
        self.assertGreater(area_sort_key('General'), area_sort_key('Area X'))


class ClusterLabelTests(SimpleTestCase):

    def test_the_facets_and_the_example_come_apart(self):
        parts = split_cluster_label('Area II {0} Certificate {0} eg. QA Staff uploads'.format(SEP))
        self.assertEqual(parts['facets'], ['Area II', 'Certificate'])
        self.assertEqual(parts['sample'], 'QA Staff uploads')

    def test_an_example_containing_a_separator_survives(self):
        """A title may hold the separator itself; it is one title, not two facets."""
        parts = split_cluster_label('Document {0} eg. SOCIOLOGY {0} COMPARATIVE ANALYSIS'.format(SEP))
        self.assertEqual(parts['facets'], ['Document'])
        self.assertEqual(parts['sample'], 'SOCIOLOGY {0} COMPARATIVE ANALYSIS'.format(SEP))

    def test_a_label_with_no_example_keeps_its_facets(self):
        self.assertEqual(split_cluster_label('Cluster 7'),
                         {'facets': ['Cluster 7'], 'sample': ''})

    def test_an_empty_label_is_not_an_error(self):
        self.assertEqual(split_cluster_label(''), {'facets': [], 'sample': ''})


def staff_user():
    user = User.objects.create_user('sel_head', 'h@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = 'qa_staff'
    user.profile.save()
    return user


class AreaCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        for code, name in (('Area V', 'Research'), ('Area IX', 'Laboratories'),
                           ('Area X', 'Administration'), ('Area II', 'Faculty')):
            AccreditationArea.objects.get_or_create(area_code=code, defaults={'area_name': name})
        cls.staff = staff_user()

    def response(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:area_submissions'))

    def test_the_cards_are_in_numeral_order(self):
        codes = [a['obj'].area_code for a in self.response().context['areas']]
        self.assertEqual(codes.index('Area V') < codes.index('Area IX'), True)
        self.assertLess(codes.index('Area IX'), codes.index('Area X'))

    def test_an_area_with_nobody_assigned_says_so(self):
        """An empty bar labelled 0/0 read as no progress, not as not applicable."""
        html = self.response().content.decode()
        self.assertIn('No faculty assigned', html)
        self.assertNotIn('0/0', html)

    def test_the_progress_figure_names_what_it_counts(self):
        """Beside a file count, a bare 0/1 read as a contradiction."""
        area = AccreditationArea.objects.get(area_code='Area II')
        faculty = User.objects.create_user('sel_fac', 'f@example.com', 'Str0ng-Passw0rd!')
        faculty.profile.role = 'faculty'
        faculty.profile.save()
        faculty.profile.assigned_areas.add(area)
        self.assertIn('<small>faculty</small>', self.response().content.decode())

    def test_an_area_with_no_files_is_marked_as_such(self):
        """Eight of the ten real areas are empty and carried the weight of the two that are not."""
        response = self.response()
        empty = sum(1 for a in response.context['areas'] if not a['file_count'])
        self.assertEqual(response.content.decode().count('qa-sel-card--empty'), empty)
        self.assertGreater(empty, 0)

    def test_an_area_holding_files_is_not_marked_empty(self):
        area = AccreditationArea.objects.get(area_code='Area II')
        Document.objects.create(title='Evidence', file='uploaded_documents/e.pdf', file_type='pdf',
                                year=2026, document_type='Report', acc_area=area, qa_area='Area II')
        response = self.response()
        filled = [a for a in response.context['areas'] if a['file_count']]
        self.assertEqual([a['obj'].area_code for a in filled], ['Area II'])
        empty = sum(1 for a in response.context['areas'] if not a['file_count'])
        self.assertEqual(response.content.decode().count('qa-sel-card--empty'), empty)


class ClusterCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = staff_user()
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        for number, size in ((0, 1), (1, 5), (2, 2)):
            for n in range(size):
                Document.objects.create(
                    title='Doc {0}-{1}'.format(number, n),
                    file='uploaded_documents/{0}{1}.pdf'.format(number, n),
                    file_type='pdf', year=2026, document_type='Report',
                    acc_area=cls.area, qa_area='Area II', cluster_label=number)
            ClusterResult.objects.create(
                document=Document.objects.filter(cluster_label=number).first(),
                cluster_number=number,
                cluster_label='Area II {0} Report {0} eg. Doc {1}-0'.format(SEP, number),
                top_keywords=[])

    def context(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:clusters')).context

    def test_the_biggest_group_comes_first(self):
        """The order was the K-Means index, which means nothing to a reader."""
        self.assertEqual([c['number'] for c in self.context()['clusters']], [1, 2, 0])

    def test_each_card_knows_its_size_against_the_largest(self):
        by_number = {c['number']: c for c in self.context()['clusters']}
        self.assertEqual(by_number[1]['size_pct'], 100)
        self.assertEqual(by_number[2]['size_pct'], 40)
        self.assertEqual(by_number[0]['size_pct'], 20)

    def test_the_example_document_is_separated_from_the_facets(self):
        first = self.context()['clusters'][0]
        self.assertEqual(first['facets'], ['Area II', 'Report'])
        self.assertEqual(first['sample'], 'Doc 1-0')

    def test_the_page_counts_its_single_document_groups(self):
        summary = self.context()['summary']
        self.assertEqual(summary['singletons'], 1)
        self.assertEqual(summary['largest_cluster'], 5)

    def test_the_facets_are_rendered_apart_from_the_title(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('documents:clusters')).content.decode()
        self.assertIn('qa-sel-card-facets', html)
        self.assertIn('<span class="qa-sel-card-facet">Area II</span>', html)


class SelectionCardStyleTests(SimpleTestCase):
    """The stylesheet rules both grids depend on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (settings.BASE_DIR / 'static' / 'css' / 'selection-cards.css').read_text(encoding='utf-8')

    def test_the_title_wraps_instead_of_being_clipped(self):
        self.assertIn('-webkit-line-clamp: 2;', self.css)
        self.assertNotIn('white-space: nowrap;\n    overflow: hidden;\n    text-overflow: ellipsis;',
                         self.css)

    def test_the_card_does_not_shrink_on_a_wider_screen(self):
        self.assertNotIn('minmax(152px, 1fr)', self.css)
        self.assertIn('minmax(190px, 1fr)', self.css)

    def test_the_status_slot_is_one_height_either_way(self):
        self.assertIn('.qa-sel-card-progress {', self.css)
        self.assertIn('min-height: 16px;', self.css)


class ClusterSortTests(TestCase):
    """
    The order was applied silently, which reads as no order at all.

    Largest-first is right -- the cluster number is the index K-Means assigned,
    not a rank -- but with it applied invisibly the grid opens C14, C5, C26 and
    a reader has no way to tell a deliberate order from a shuffled one, or to
    ask for the sequence back.
    """

    @classmethod
    def setUpTestData(cls):
        cls.staff = staff_user()
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        for number, size in ((0, 1), (1, 5), (2, 2)):
            for n in range(size):
                Document.objects.create(
                    title='Doc {0}-{1}'.format(number, n),
                    file='uploaded_documents/s{0}{1}.pdf'.format(number, n),
                    file_type='pdf', year=2026, document_type='Report',
                    acc_area=cls.area, qa_area='Area II', cluster_label=number)

    def order(self, query=''):
        self.client.force_login(self.staff)
        page = self.client.get(reverse('documents:clusters') + query)
        return [c['number'] for c in page.context['clusters']], page

    def test_the_default_is_the_largest_group_first(self):
        numbers, page = self.order()
        self.assertEqual(numbers, [1, 2, 0])
        self.assertEqual(page.context['sort_value'], 'size')
        self.assertEqual(page.context['sort_label'], 'Largest first')

    def test_a_reader_can_ask_for_the_numbers_in_sequence(self):
        numbers, page = self.order('?sort=number')
        self.assertEqual(numbers, [0, 1, 2])
        self.assertEqual(page.context['sort_label'], 'Cluster number')

    def test_the_smallest_groups_can_come_first(self):
        self.assertEqual(self.order('?sort=smallest')[0], [0, 2, 1])

    def test_an_unknown_order_falls_back_to_the_default(self):
        numbers, page = self.order('?sort=nonsense')
        self.assertEqual(numbers, [1, 2, 0])
        self.assertEqual(page.context['sort_value'], 'size')

    def test_the_order_in_force_is_named_on_the_page(self):
        html = self.order('?sort=number')[1].content.decode()
        self.assertIn('Sorted by', html)
        self.assertIn('<span class="qa-sel-sort-current">Cluster number</span>', html)

    def test_every_order_is_offered(self):
        html = self.order()[1].content.decode()
        for label in ('Largest first', 'Smallest first', 'Cluster number', 'Recently updated'):
            self.assertIn(label, html)

    def test_choosing_a_cluster_keeps_the_order(self):
        """A card link that dropped the sort sent the reader back to the default."""
        html = self.order('?sort=number')[1].content.decode()
        self.assertIn('?cluster=1&amp;sort=number', html)
        self.assertIn('data-sort="number"', html)

    def test_the_least_recently_touched_group_sorts_last_by_date(self):
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now()
        Document.objects.filter(cluster_label=1).update(uploaded_at=now - timedelta(days=30))
        Document.objects.filter(cluster_label=2).update(uploaded_at=now - timedelta(days=2))
        Document.objects.filter(cluster_label=0).update(uploaded_at=now)
        self.assertEqual(self.order('?sort=recent')[0], [0, 2, 1])

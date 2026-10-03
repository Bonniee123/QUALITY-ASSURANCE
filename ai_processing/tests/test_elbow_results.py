"""
The Elbow chart on the Document Analysis page: the right k, seen by every Admin,
and honest about what actually chose each group's k.

* The elbow was reported one k too high: the curvature index was offset by 2
  instead of 1 (S-CL-01).
* The chart lived only in the session of the person whose page ran the pipeline
  in the foreground. With background jobs -- the default -- nobody saw it, and a
  second Admin never did (S-CL-02).
* The chart covers only the largest group, and k is normally chosen by the
  silhouette score, so its "optimal k" could disagree with the clusters formed,
  with nothing on the page saying so (S-CL-03).
"""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from ai_processing.elbow_service import find_elbow_point
from documents.ai_pipeline import CLUSTERING_RUN_METRIC, last_elbow_summary, run_full_ai_pipeline
from documents.models import Document, ProcessingMetric
from qa_structure.models import AccreditationArea


class ElbowPointTests(SimpleTestCase):

    def test_the_elbow_is_the_k_at_the_curvature_peak(self):
        # Three well-separated topics: inertia drops steeply to k=3, then flattens.
        k_values = [2, 3, 4, 5, 6]
        inertias = [9.0, 3.0, 2.6, 2.3, 2.1]
        # Second differences, centred on k=3..5: 5.6, 0.1, 0.1 -> the peak is at k=3.
        self.assertEqual(find_elbow_point(k_values, inertias), 3)

    def test_a_later_elbow(self):
        self.assertEqual(find_elbow_point([2, 3, 4, 5, 6], [10.0, 9.0, 8.0, 2.0, 1.8]), 5)

    def test_too_few_points_returns_the_first_k(self):
        self.assertEqual(find_elbow_point([2, 3], [5.0, 1.0]), 2)


TOPICS = {
    'faculty': 'faculty qualifications ranks development plan training workshop professor instructor',
    'library': 'library holdings periodicals circulation librarian catalog acquisitions reading',
    'laboratory': 'laboratory equipment chemicals fume hood safety glassware inspection calibration',
}


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=False)
class ElbowSavedWithTheRunTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        area, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        for topic, words in TOPICS.items():
            for i in range(4):
                Document.objects.create(
                    title=f'{topic} report {i}', file=f'uploaded_documents/{topic}{i}.pdf', file_type='pdf',
                    year=2026, document_type='Report', acc_area=area, qa_area='Area III',
                    extracted_text=f'{words} {words} note {i} ' * 20)
        for username in ('admin_one', 'admin_two'):
            user = User.objects.create_user(username, password='pass12345')
            user.profile.role = 'admin'
            user.profile.save()

    def test_a_background_run_keeps_its_elbow_result(self):
        run_full_ai_pipeline(None)  # no request: exactly how the background job runs it
        elbow = last_elbow_summary()
        self.assertIsNotNone(elbow)
        self.assertEqual(elbow['group'], 'Area III · Report')
        self.assertEqual(elbow['group_size'], 12)
        self.assertIn(elbow['k_method'], ('silhouette', 'elbow'))
        self.assertEqual(elbow['formed'], len(set(Document.objects.values_list('cluster_label', flat=True))))

    def test_every_admin_sees_the_chart(self):
        run_full_ai_pipeline(None)
        for username in ('admin_one', 'admin_two'):
            self.client.force_login(User.objects.get(username=username))
            response = self.client.get(reverse('ai_processing:list'))
            self.assertContains(response, 'Optimal k (Elbow) =')
            self.assertContains(response, 'Elbow curve of the largest group, Area III · Report (12 documents).')
            self.assertContains(response, 'Its clusters used k =')

    def test_no_chart_before_any_run(self):
        self.assertIsNone(last_elbow_summary())
        self.client.force_login(User.objects.get(username='admin_one'))
        self.assertNotContains(self.client.get(reverse('ai_processing:list')), 'Optimal k (Elbow)')

    def test_a_run_recorded_before_this_change_still_reads(self):
        ProcessingMetric.objects.create(metric_name=CLUSTERING_RUN_METRIC, metric_value=3, unit='documents',
                                        meta={'backend': 'tfidf'})
        self.assertIsNone(last_elbow_summary())

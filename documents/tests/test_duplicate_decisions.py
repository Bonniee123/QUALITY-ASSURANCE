"""
Staff duplicate decisions survive re-processing, and each pair is announced once.

Measured before the change on a copy of the live data:

* Confirm a duplicate, run AI Processing: back to "Needs review" (S-DUP-03).
* Dismiss a flag, run AI Processing: flagged again, and the uploader and every
  staff member notified again (S-DUP-03, S-DUP-15).
* Every run re-announced every visually matched image, because the text pass
  cleared images first and the visual pass then saw each flag as new: 854
  alerts in 40 minutes of ordinary use (S-DUP-15).
* Archived versions took part in the comparison, so a current document could be
  sent for review against a match nobody could open (S-DUP-04).
* Deleting one document of a flagged pair left the other on "Needs review" with
  nothing to review (S-DUP-02).
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from documents.ai_pipeline import run_full_ai_pipeline
from documents.models import BackgroundJob, Document
from notifications.models import Notification

BODY = ('The quality assurance office maintains records of every accreditation area '
        'including faculty credentials research output and extension work. ') * 12
OTHER = ('Laboratory safety inspection covering chemical storage, fume hoods, eye wash '
         'stations and glassware handling in the science building this semester. ') * 12


def make_user(username, role):
    user = User.objects.create_user(username, f'{username}@example.com', 'pass12345')
    user.profile.role = role
    user.profile.save()
    return user


def make_doc(title, **extra):
    fields = dict(title=title, file=f'uploaded_documents/{title}.pdf', file_type='pdf',
                  year=2026, document_type='Report')
    fields.update(extra)
    return Document.objects.create(**fields)


def statuses():
    return dict(Document.objects.values_list('title', 'duplicate_status'))


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=False)
class DecisionsSurviveReprocessingTests(TestCase):

    def setUp(self):
        self.head = make_user('qatest_head', 'qa_staff')
        self.client.force_login(self.head)
        self.a = make_doc('Report', extracted_text=BODY, uploaded_by=self.head)
        self.b = make_doc('Report copy', extracted_text=BODY, uploaded_by=self.head)
        self.c = make_doc('Lab safety', extracted_text=OTHER)
        run_full_ai_pipeline(None)
        self.assertEqual(statuses()['Report copy'], 'possible')

    def test_a_confirmed_duplicate_stays_confirmed(self):
        self.client.post(reverse('documents:duplicate_confirm', args=[self.b.pk]))
        run_full_ai_pipeline(None)
        self.assertEqual(statuses()['Report copy'], 'confirmed_dup')

    def test_a_dismissed_flag_stays_dismissed_and_is_not_announced_again(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.b.pk]))
        sent = Notification.objects.count()
        run_full_ai_pipeline(None)
        run_full_ai_pipeline(None)
        self.assertEqual(statuses()['Report copy'], 'none')
        self.assertEqual(Notification.objects.count(), sent)

    def test_a_new_match_after_a_dismissal_is_flagged_and_announced(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.b.pk]))
        sent = Notification.objects.count()
        make_doc('Report third copy', extracted_text=BODY)
        run_full_ai_pipeline(None)
        self.assertEqual(statuses()['Report copy'], 'possible')
        self.assertGreater(Notification.objects.count(), sent)

    def test_re_running_announces_nothing_new(self):
        sent = Notification.objects.count()
        run_full_ai_pipeline(None)
        run_full_ai_pipeline(None)
        self.assertEqual(Notification.objects.count(), sent)

    def test_a_new_pair_is_announced_to_staff_once(self):
        # Both documents of the pair were flagged in setUp's run; staff heard once.
        self.assertEqual(Notification.objects.filter(user=self.head, category='duplicate').count(), 1)

    def test_deleting_one_of_a_pair_clears_the_other(self):
        self.client.post(reverse('documents:delete', args=[self.a.pk]))
        self.b.refresh_from_db()
        self.assertEqual((self.b.duplicate_status, self.b.similar_documents), ('none', []))

    def test_bulk_deleting_one_of_a_pair_clears_the_other(self):
        self.client.post(reverse('documents:bulk_delete'), {'document_ids': [self.b.pk]})
        self.a.refresh_from_db()
        self.assertEqual((self.a.duplicate_status, self.a.similar_documents), ('none', []))

    def test_the_refresh_command_keeps_decisions_too(self):
        from documents.jobs import _refresh_duplicate_flags
        self.client.post(reverse('documents:duplicate_confirm', args=[self.b.pk]))
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.a.pk]))
        _refresh_duplicate_flags()
        self.assertEqual((statuses()['Report copy'], statuses()['Report']), ('confirmed_dup', 'none'))


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=False)
class EarlierDecisionsTests(TestCase):
    """Decisions made before they were recorded per match are honoured too."""

    def test_a_flag_dismissed_earlier_is_not_raised_again(self):
        a = make_doc('Report', extracted_text=BODY)
        b = make_doc('Report copy', extracted_text=BODY)
        make_doc('Lab safety', extracted_text=OTHER)
        # What a Dismiss left behind: status cleared, list kept, no per-match mark.
        Document.objects.filter(pk=b.pk).update(
            duplicate_status='none', similar_documents=[{'id': a.pk, 'title': 'Report', 'similarity': 1.0}])
        Document.objects.filter(pk=a.pk).update(
            duplicate_status='confirmed_dup', similar_documents=[{'id': b.pk, 'title': 'Report copy', 'similarity': 1.0}])
        run_full_ai_pipeline(None)
        self.assertEqual((statuses()['Report copy'], statuses()['Report']), ('none', 'confirmed_dup'))


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=False)
class ImageAlertFloodTests(TestCase):

    def test_matching_images_are_announced_once_not_on_every_run(self):
        head = make_user('qatest_head', 'qa_staff')
        for name in ('chart', 'chart again'):
            make_doc(name, file=f'uploaded_documents/{name}.png', file_type='png',
                     extracted_text='', image_phash='aaaabbbbccccdddd', uploaded_by=head)
        make_doc('Report', extracted_text=BODY)
        make_doc('Lab safety', extracted_text=OTHER)
        run_full_ai_pipeline(None)
        after_first = Notification.objects.count()
        self.assertEqual(Notification.objects.filter(user=head).count(), 1, 'one alert for the new pair')
        for _ in range(3):
            run_full_ai_pipeline(None)
        self.assertEqual(Notification.objects.count(), after_first)
        self.assertEqual(statuses()['chart again'], 'possible')


@override_settings(AI_CLUSTER_USE_EMBEDDINGS=False)
class ArchivedVersionsTests(TestCase):

    def test_a_current_document_is_not_matched_against_an_archived_version(self):
        make_doc('Old manual', extracted_text=BODY, is_archived=True)
        make_doc('Manual', extracted_text=BODY)
        make_doc('Lab safety', extracted_text=OTHER)
        run_full_ai_pipeline(None)
        manual = Document.objects.get(title='Manual')
        self.assertEqual((manual.duplicate_status, manual.similar_documents), ('none', []))

    def test_archived_versions_are_not_clustered(self):
        old = make_doc('Old manual', extracted_text=BODY, is_archived=True, cluster_label=4,
                       duplicate_status='possible', similar_documents=[{'id': 999, 'title': 'x', 'similarity': 1.0}])
        make_doc('Manual', extracted_text=BODY)
        make_doc('Lab safety', extracted_text=OTHER)
        run_full_ai_pipeline(None)
        old.refresh_from_db()
        self.assertEqual((old.cluster_label, old.duplicate_status, old.similar_documents), (None, 'none', []))
        self.assertFalse(old.cluster_results.exists())

    def test_two_current_copies_are_still_matched(self):
        make_doc('Old manual', extracted_text=BODY, is_archived=True)
        make_doc('Manual', extracted_text=BODY)
        make_doc('Manual copy', extracted_text=BODY)
        make_doc('Lab safety', extracted_text=OTHER)
        run_full_ai_pipeline(None)
        copy = Document.objects.get(title='Manual copy')
        self.assertEqual(copy.duplicate_status, 'possible')
        self.assertEqual([m['title'] for m in copy.similar_documents], ['Manual'])


class BatchRowTitleTests(TestCase):
    """The upload page names a match only to someone who may open it."""

    def setUp(self):
        from qa_structure.models import AccreditationArea
        self.area2, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        self.area3, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})
        self.match = make_doc('Faculty Development Plan', acc_area=self.area2, qa_area='Area II')

    def row_for(self, user):
        from documents.upload_batches import batch_detail
        doc = Document.objects.create(
            title='upload', file=SimpleUploadedFile('upload.pdf', b'%PDF-1.4 x'), file_type='pdf', year=2026,
            document_type='Report', is_processed=True, duplicate_status='possible', acc_area=self.area3,
            similar_documents=[{'id': self.match.pk, 'title': self.match.title, 'similarity': 0.93}])
        job = BackgroundJob.objects.create(job_type='bulk_upload_process', created_by=user, status='completed',
                                           payload={'document_ids': [doc.pk], 'total_count': 1})
        return batch_detail(job)['files'][0]

    def test_faculty_of_another_area_are_not_shown_the_title(self):
        faculty = make_user('fac3', 'faculty')
        faculty.profile.assigned_areas.add(self.area3)
        row = self.row_for(faculty)
        self.assertEqual(row['state'], 'duplicate')
        self.assertNotIn('Faculty Development Plan', row['detail'])
        self.assertIn('93% similar to a document already in the archive', row['detail'])

    def test_staff_are(self):
        self.assertIn('Faculty Development Plan', self.row_for(make_user('head', 'qa_staff'))['detail'])

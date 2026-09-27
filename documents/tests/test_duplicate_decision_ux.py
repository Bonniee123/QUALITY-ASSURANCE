"""
Deciding a duplicate from the details modal, and being able to see that you did.

Two things made a decision feel like it had not happened.

The buttons were ordinary forms that redirected to the standalone document
page, so clicking one inside the Document Details modal closed the modal and
moved the reader somewhere else. They are still ordinary forms -- with the
script absent, or on the document page itself, they post and redirect exactly
as before -- but a request that announces itself as XHR is now answered with
JSON, which is what lets the modal post on the reader's behalf and reload the
panel in place.

And the panel looked identical afterwards. A decision records `review` on every
listed match and flips `duplicate_status`; it deliberately does not delete the
matches, because that list is the evidence for the decision. But nothing said
the decision had been taken, so seven rows of "99% of the wording matches" read
as an open question either way. The panel now leads with the outcome and folds
the rows away once there is one.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


def make_user(username, role):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    return user


class DecisionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.head = make_user('dup_head', 'qa_staff')
        cls.other = Document.objects.create(
            title='Chapter 1 2 3 QA FINAL', file='uploaded_documents/a.docx', file_type='docx',
            year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
            extracted_text='the same wording repeated for comparison ' * 12,
            is_processed=True, duplicate_status='none')
        cls.doc = Document.objects.create(
            title='Chapter 1 2 3 QA FINAL revised', file='uploaded_documents/b.docx',
            file_type='docx', year=2026, document_type='Report', acc_area=cls.area,
            qa_area='Area II', extracted_text='the same wording repeated for comparison ' * 12,
            is_processed=True, duplicate_status='possible',
            similar_documents=[{'id': cls.other.pk, 'similarity': 0.99, 'match_type': 'text'}])

    def setUp(self):
        self.client.force_login(self.head)

    def panel(self, pk=None):
        return self.client.get(
            reverse('documents:detail', args=[pk or self.doc.pk]) + '?panel=1').content.decode()

    # --- how the decision is answered ---------------------------------

    def test_a_plain_post_still_redirects_to_the_document(self):
        """The document page and a browser without the script are unchanged."""
        response = self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('documents:detail', args=[self.doc.pk]))

    def test_a_modal_post_is_answered_with_json(self):
        response = self.client.post(
            reverse('documents:duplicate_dismiss', args=[self.doc.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['duplicate_status'], 'none')
        self.assertIn('Clear', data['badge'])
        self.assertIn('kept as a separate version', data['message'])

    def test_the_modal_post_queues_no_message_for_a_later_page(self):
        """
        A queued message nobody renders is not discarded -- it waits and turns
        up at the top of whatever page is opened next.
        """
        response = self.client.post(
            reverse('documents:duplicate_confirm', args=[self.doc.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        later = self.client.get(reverse('documents:repository'))
        self.assertEqual(list(later.context['messages']), [])

    def test_the_decision_itself_is_recorded_either_way(self):
        self.client.post(reverse('documents:duplicate_confirm', args=[self.doc.pk]),
                         HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'confirmed_dup')
        self.assertEqual(self.doc.similar_documents[0]['review'], 'confirmed')
        self.assertTrue(self.doc.similar_documents[0]['reviewed_at'],
                        'a decision has to carry its date')

    def test_the_matches_are_kept_as_the_record_of_what_was_compared(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]),
                         HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.doc.refresh_from_db()
        self.assertEqual(len(self.doc.similar_documents), 1)

    def test_faculty_cannot_decide(self):
        """The buttons are staff work; the route has to say so too."""
        self.client.force_login(make_user('dup_faculty', 'faculty'))
        response = self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]),
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertIn(response.status_code, (302, 403))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.duplicate_status, 'possible')

    # --- what the panel says afterwards --------------------------------

    def test_an_undecided_panel_says_so_and_shows_the_rows(self):
        html = self.panel()
        self.assertIn('Not reviewed yet', html)
        self.assertIn('similar document', html)
        self.assertNotIn('<details', html)

    def test_a_decided_panel_leads_with_the_outcome(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        html = self.panel()
        self.assertIn('kept as separate versions', html)
        self.assertNotIn('Not reviewed yet', html)

    def test_a_confirmed_panel_says_confirmed(self):
        self.client.post(reverse('documents:duplicate_confirm', args=[self.doc.pk]))
        self.assertIn('confirmed as a duplicate', self.panel())

    def test_the_rows_are_folded_away_once_decided(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        html = self.panel()
        self.assertIn('<details', html)
        self.assertIn('this was compared against', html)
        # Folded, not deleted: the evidence is still in the page.
        self.assertIn(self.other.title, html)

    def test_the_summary_counts_and_states_the_measurement(self):
        html = self.panel()
        self.assertIn('99%', html)
        self.assertIn('of the wording', html)

    def test_the_decision_date_is_shown(self):
        self.client.post(reverse('documents:duplicate_dismiss', args=[self.doc.pk]))
        from django.utils import timezone
        self.assertIn(timezone.localtime(timezone.now()).strftime('%b %d, %Y'), self.panel())

    def test_a_document_with_no_matches_has_no_summary(self):
        clean = Document.objects.create(
            title='Standalone', file='uploaded_documents/c.docx', file_type='docx', year=2026,
            document_type='Report', acc_area=self.area, qa_area='Area II', is_processed=True)
        self.assertNotIn('Not reviewed yet', self.panel(clean.pk))


class TableHookTests(TestCase):
    """The row behind the modal has to be repaintable."""

    @classmethod
    def setUpTestData(cls):
        cls.head = make_user('dup_table', 'qa_staff')
        cls.doc = Document.objects.create(
            title='Row document', file='uploaded_documents/d.docx', file_type='docx', year=2026,
            document_type='Report', is_processed=True, duplicate_status='possible')

    def test_the_repository_duplicate_cell_is_addressed_by_document(self):
        self.client.force_login(self.head)
        html = self.client.get(reverse('documents:repository')).content.decode()
        self.assertIn('data-qa-dup-badge="%d"' % self.doc.pk, html)


class ScriptTests(SimpleTestCase):
    """What the modal's script does with the two forms."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (settings.BASE_DIR / 'static' / 'js' / 'doc-detail.js').read_text(encoding='utf-8')

    def test_it_only_intercepts_forms_inside_the_modal(self):
        """On the document page itself the same form must post normally."""
        self.assertIn("var form = e.target.closest('.js-qa-duplicate-decision');", self.js)
        self.assertIn('!bodyEl.contains(form)', self.js)

    def test_it_announces_itself_as_xhr(self):
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", self.js)
        self.assertIn("'X-CSRFToken': csrfToken(form)", self.js)

    def test_it_reloads_the_panel_and_repaints_the_row(self):
        self.assertIn('reloadPanel(docId);', self.js)
        self.assertIn('repaintRowBadge(docId, data.badge);', self.js)

    def test_a_failure_re_enables_the_buttons_and_says_so(self):
        self.assertIn('could not be saved', self.js)

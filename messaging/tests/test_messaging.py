"""
Tests for direct messaging.

The important one is `test_attached_document_is_withheld_from_a_reader_without_access`:
messaging is deliberately open, so the attachment check is the only place the
software itself could hand over something the reader may not see.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea

from messaging.models import Thread, ThreadMessage, unread_total_for


class MessagingTestBase(TestCase):
    def setUp(self):
        self.qa = User.objects.create_user('m_qa', 'qa@e.com', 'testpass123',
                                           first_name='Quinn', last_name='Adams')
        self.qa.profile.role = 'qa_staff'
        self.qa.profile.save()

        self.faculty = User.objects.create_user('m_fac', 'fac@e.com', 'testpass123',
                                                first_name='Faith', last_name='Cruz')
        self.faculty.profile.role = 'faculty'
        self.faculty.profile.save()

        self.outsider = User.objects.create_user('m_out', 'out@e.com', 'testpass123')
        self.outsider.profile.role = 'faculty'
        self.outsider.profile.save()

    def login(self, user):
        client = self.client_class()
        client.login(username=user.get_username(), password='testpass123')
        return client

    def start_thread(self, client, other):
        response = client.post(reverse('messaging:thread_start'),
                               json.dumps({'user_id': other.pk}),
                               content_type='application/json')
        return response.json()['thread']['id']

    def send(self, client, thread_id, body, document_id=None):
        payload = {'body': body}
        if document_id:
            payload['document_id'] = document_id
        return client.post(f'/messages/threads/{thread_id}/send/',
                           json.dumps(payload), content_type='application/json')


class ConversationTests(MessagingTestBase):
    def test_qa_can_message_a_named_faculty_member(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        response = self.send(qa, thread_id, 'Please re-upload that report.')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['message']['mine'])

    def test_faculty_can_reply(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Please re-upload that report.')

        faculty = self.login(self.faculty)
        response = self.send(faculty, thread_id, 'Uploading it now.')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Thread.objects.get(pk=thread_id).visible_messages().count(), 2)

    def test_starting_twice_reuses_the_same_thread(self):
        qa = self.login(self.qa)
        first = self.start_thread(qa, self.faculty)
        second = self.start_thread(qa, self.faculty)
        self.assertEqual(first, second)

    def test_cannot_message_yourself(self):
        qa = self.login(self.qa)
        response = qa.post(reverse('messaging:thread_start'),
                           json.dumps({'user_id': self.qa.pk}),
                           content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_cannot_start_with_a_deactivated_account(self):
        self.faculty.profile.status = 'inactive'
        self.faculty.profile.save()
        qa = self.login(self.qa)
        response = qa.post(reverse('messaging:thread_start'),
                           json.dumps({'user_id': self.faculty.pk}),
                           content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_empty_message_is_rejected(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.assertEqual(self.send(qa, thread_id, '   ').status_code, 400)


class ThreadPrivacyTests(MessagingTestBase):
    """A thread belongs to its participants and nobody else."""

    def test_non_participant_cannot_read_a_thread(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Private note.')

        outsider = self.login(self.outsider)
        # 404 rather than 403: confirming the thread exists is itself information.
        self.assertEqual(outsider.get(f'/messages/threads/{thread_id}/').status_code, 404)

    def test_non_participant_cannot_post_into_a_thread(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        outsider = self.login(self.outsider)
        self.assertEqual(self.send(outsider, thread_id, 'Injected.').status_code, 404)
        self.assertEqual(Thread.objects.get(pk=thread_id).visible_messages().count(), 0)

    def test_thread_list_shows_only_your_own(self):
        qa = self.login(self.qa)
        self.start_thread(qa, self.faculty)
        outsider = self.login(self.outsider)
        self.assertEqual(outsider.get(reverse('messaging:thread_list')).json()['threads'], [])


class AttachmentAccessTests(MessagingTestBase):
    """
    The security-relevant behaviour.

    Messaging is open by design, so nothing stops someone naming a document in
    plain text. What must not happen is the *system* rendering a document to a
    reader who cannot open it.
    """

    def setUp(self):
        super().setUp()
        # get_or_create: a data migration already seeds the ten AACCUP areas, so
        # creating them outright collides on the unique area_code.
        area_ii, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        area_ix, _ = AccreditationArea.objects.get_or_create(
            area_code='Area IX', defaults={'area_name': 'Laboratories'})
        self.faculty.profile.assigned_areas.set([area_ii])

        self.restricted = Document.objects.create(
            title='Laboratory Safety Audit 2025',
            file='uploaded_documents/2025/01/lab.pdf',
            file_type='pdf', year=2025, document_type='Report', acc_area=area_ix,
        )
        self.shared = Document.objects.create(
            title='Faculty Development Plan',
            file='uploaded_documents/2025/01/fac.pdf',
            file_type='pdf', year=2025, document_type='Plan', acc_area=area_ii,
        )

    def test_attached_document_is_withheld_from_a_reader_without_access(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'See this.', document_id=self.restricted.pk)

        faculty = self.login(self.faculty)
        response = faculty.get(f'/messages/threads/{thread_id}/')
        message = response.json()['messages'][-1]

        self.assertIsNone(message['document'])
        self.assertTrue(message['document_withheld'])
        # and the title must not appear anywhere in the payload
        self.assertNotIn('Laboratory Safety Audit', response.content.decode())

    def test_sender_still_sees_their_own_attachment(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'See this.', document_id=self.restricted.pk)
        message = qa.get(f'/messages/threads/{thread_id}/').json()['messages'][-1]
        self.assertEqual(message['document']['title'], 'Laboratory Safety Audit 2025')

    def test_permitted_attachment_is_shown_in_full(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'This one.', document_id=self.shared.pk)

        faculty = self.login(self.faculty)
        message = faculty.get(f'/messages/threads/{thread_id}/').json()['messages'][-1]
        self.assertEqual(message['document']['title'], 'Faculty Development Plan')
        self.assertFalse(message['document_withheld'])

    def test_sender_cannot_attach_a_document_they_cannot_open(self):
        faculty = self.login(self.faculty)
        thread_id = self.start_thread(faculty, self.qa)
        self.send(faculty, thread_id, 'Look.', document_id=self.restricted.pk)
        message = ThreadMessage.objects.filter(thread_id=thread_id).last()
        self.assertIsNone(message.document_id)


class UnreadTests(MessagingTestBase):
    def test_unread_counts_for_recipient_not_sender(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'One.')
        self.send(qa, thread_id, 'Two.')

        self.assertEqual(unread_total_for(self.faculty), 2)
        self.assertEqual(unread_total_for(self.qa), 0)

    def test_opening_a_thread_clears_its_unread(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'One.')

        faculty = self.login(self.faculty)
        faculty.get(f'/messages/threads/{thread_id}/')
        self.assertEqual(unread_total_for(self.faculty), 0)


class DeletionTests(MessagingTestBase):
    def test_sender_can_soft_delete_and_the_row_survives(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        message_id = self.send(qa, thread_id, 'Oops.').json()['message']['id']

        qa.post(f'/messages/threads/{thread_id}/messages/{message_id}/delete/')
        message = ThreadMessage.objects.get(pk=message_id)
        self.assertTrue(message.is_deleted)
        self.assertEqual(Thread.objects.get(pk=thread_id).visible_messages().count(), 0)

    def test_cannot_delete_someone_elses_message(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        message_id = self.send(qa, thread_id, 'Mine.').json()['message']['id']

        faculty = self.login(self.faculty)
        response = faculty.post(f'/messages/threads/{thread_id}/messages/{message_id}/delete/')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ThreadMessage.objects.get(pk=message_id).is_deleted)


class PageTests(MessagingTestBase):
    def test_inbox_renders_for_every_role(self):
        for user in (self.qa, self.faculty):
            client = self.login(user)
            response = client.get(reverse('messaging:inbox'))
            self.assertEqual(response.status_code, 200)
            body = response.content.decode()
            self.assertNotIn('{{', body)
            self.assertNotIn('{%', body)

    def test_people_list_excludes_self_and_inactive(self):
        self.outsider.profile.status = 'inactive'
        self.outsider.profile.save()
        qa = self.login(self.qa)
        people = qa.get(reverse('messaging:people')).json()['people']
        ids = [p['id'] for p in people]
        self.assertNotIn(self.qa.pk, ids)
        self.assertNotIn(self.outsider.pk, ids)
        self.assertIn(self.faculty.pk, ids)

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(reverse('messaging:inbox')).status_code, 302)


class SearchTests(MessagingTestBase):
    """
    Finding a person you have never messaged.

    The search has to reach the whole roster, not only people already in a
    thread, and it has to accept the name as it is *displayed*. Users are shown
    by full name while the database stores first and last separately, so a plain
    substring search over each column found nothing for "Quinn Adams" -- which is
    what made the box look like it could not see most of the users.
    """

    def setUp(self):
        super().setUp()
        self.searcher = self.login(self.faculty)

    def people_for(self, query):
        response = self.searcher.get(reverse('messaging:people'), {'q': query})
        return [p['name'] for p in response.json()['people']]

    def threads_for(self, query):
        response = self.searcher.get(reverse('messaging:thread_list'), {'q': query})
        return [t['name'] for t in response.json()['threads']]

    def test_full_name_finds_a_person_with_no_thread(self):
        self.assertIn('Quinn Adams', self.people_for('Quinn Adams'))

    def test_each_name_part_finds_the_person(self):
        for query in ('Quinn', 'Adams', 'quinn adams', 'ADAMS', 'm_qa'):
            self.assertIn('Quinn Adams', self.people_for(query), msg=f'query={query!r}')

    def test_word_order_does_not_matter(self):
        self.assertIn('Quinn Adams', self.people_for('Adams Quinn'))

    def test_extra_word_narrows_rather_than_widens(self):
        # 'Quinn Nobody' must not match on 'Quinn' alone.
        self.assertEqual(self.people_for('Quinn Nobody'), [])

    def test_a_person_is_findable_even_with_no_conversation(self):
        self.assertEqual(Thread.objects.count(), 0)
        self.assertIn('Quinn Adams', self.people_for('Quinn Adams'))

    def test_search_finds_an_existing_thread_by_full_name(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Anything.')
        self.assertEqual(self.threads_for('Quinn Adams'), ['Quinn Adams'])

    def test_searching_your_own_name_does_not_return_every_thread(self):
        # Threads are listed under the *other* participant, so matching yourself
        # would return everything under names that do not match the query.
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Anything.')
        self.assertEqual(self.threads_for('Faith Cruz'), [])

    def test_thread_search_still_matches_message_text(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Please re-upload the syllabus.')
        self.assertEqual(self.threads_for('syllabus'), ['Quinn Adams'])

    def test_no_match_returns_nothing(self):
        self.assertEqual(self.people_for('zzzznotarealname'), [])

    def test_blank_query_returns_the_whole_roster(self):
        names = self.people_for('')
        self.assertIn('Quinn Adams', names)
        self.assertIn('m_out', names)


class AreaQueryTests(TestCase):
    """Turning what someone types into an area code, with no database in sight."""

    def test_a_number_becomes_the_roman_code(self):
        from messaging.area_search import area_codes_for
        for query in ('Area #5', 'Area 5', 'area 5', '5', '#5', 'area no. 5'):
            self.assertEqual(area_codes_for(query), ['Area V'], msg=f'query={query!r}')

    def test_roman_input_is_accepted(self):
        from messaging.area_search import area_codes_for
        self.assertEqual(area_codes_for('Area IX'), ['Area IX'])
        self.assertEqual(area_codes_for('area ix'), ['Area IX'])

    def test_double_digit_areas(self):
        from messaging.area_search import area_codes_for
        self.assertEqual(area_codes_for('10'), ['Area X'])
        self.assertEqual(area_codes_for('Area 10'), ['Area X'])

    def test_a_name_is_not_an_area_reference(self):
        from messaging.area_search import area_codes_for
        for query in ('Marco', 'Quinn Adams', '', 'area', 'faculty'):
            self.assertEqual(area_codes_for(query), [], msg=f'query={query!r}')

    def test_a_bare_single_letter_is_not_treated_as_a_numeral(self):
        # 'I' is a Roman numeral but far more likely to be someone typing a name.
        from messaging.area_search import area_codes_for
        self.assertEqual(area_codes_for('I'), [])
        self.assertEqual(area_codes_for('Area I'), ['Area I'])

    def test_to_roman(self):
        from messaging.area_search import to_roman
        self.assertEqual([to_roman(n) for n in (1, 4, 5, 9, 10)],
                         ['I', 'IV', 'V', 'IX', 'X'])


class AreaSearchTests(MessagingTestBase):
    """Finding people by the area they are assigned to."""

    def setUp(self):
        super().setUp()
        self.area_v, _ = AccreditationArea.objects.get_or_create(
            area_code='Area V', defaults={'area_name': 'Research'})
        self.area_ii, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        self.area_vii, _ = AccreditationArea.objects.get_or_create(
            area_code='Area VII', defaults={'area_name': 'Library'})

        self.faculty.profile.assigned_areas.set([self.area_v])       # Faith Cruz
        self.outsider.profile.assigned_areas.set([self.area_ii])     # m_out
        self.searcher = self.login(self.qa)

    def people_for(self, query):
        return self.searcher.get(reverse('messaging:people'), {'q': query}).json()

    def test_area_number_returns_that_areas_members(self):
        for query in ('Area #5', 'Area 5', '5', 'Area V'):
            payload = self.people_for(query)
            self.assertTrue(payload['area_search'], msg=f'query={query!r}')
            self.assertEqual([p['name'] for p in payload['people']],
                             ['Faith Cruz'], msg=f'query={query!r}')

    def test_area_name_also_resolves(self):
        payload = self.people_for('Research')
        self.assertTrue(payload['area_search'])
        self.assertEqual([p['name'] for p in payload['people']], ['Faith Cruz'])

    def test_results_are_labelled_with_the_area(self):
        person = self.people_for('Area 5')['people'][0]
        self.assertEqual(person['area_label'], 'Area V')
        self.assertEqual(person['areas'], ['Area V'])

    def test_people_outside_the_area_are_excluded(self):
        names = [p['name'] for p in self.people_for('Area 5')['people']]
        self.assertNotIn('m_out', names)          # assigned to Area II
        self.assertNotIn('Quinn Adams', names)    # QA Head, no areas

    def test_an_empty_area_says_so(self):
        payload = self.people_for('Area 7')
        self.assertTrue(payload['area_search'])
        self.assertEqual(payload['people'], [])
        self.assertEqual(payload['area_names'], ['Area VII - Library'])

    def test_a_name_search_is_unaffected(self):
        payload = self.people_for('Faith')
        self.assertFalse(payload['area_search'])
        self.assertEqual([p['name'] for p in payload['people']], ['Faith Cruz'])

    def test_existing_threads_are_found_by_area(self):
        thread_id = self.start_thread(self.searcher, self.faculty)
        self.send(self.searcher, thread_id, 'About the research file.')
        threads = self.searcher.get(reverse('messaging:thread_list'),
                                    {'q': 'Area 5'}).json()['threads']
        self.assertEqual([t['name'] for t in threads], ['Faith Cruz'])


class LiveSyncTests(MessagingTestBase):
    """The interface stays current without the page being reloaded."""

    def sync(self, client, **params):
        return client.get(reverse('messaging:sync'), params).json()

    def test_counts_only_is_cheap_and_has_no_thread_data(self):
        payload = self.sync(self.login(self.qa), counts=1)
        self.assertEqual(set(payload), {'unread_messages', 'unread_notifications'})

    def test_a_new_message_arrives_without_reloading(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        faculty = self.login(self.faculty)
        self.assertEqual(self.sync(faculty, thread=thread_id, after=0)['messages'], [])

        self.send(qa, thread_id, 'Arrived while you were looking.')
        fresh = self.sync(faculty, thread=thread_id, after=0)['messages']
        self.assertEqual([m['body'] for m in fresh], ['Arrived while you were looking.'])

    def test_only_messages_after_the_cursor_are_returned(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        first = self.send(qa, thread_id, 'One.').json()['message']['id']
        self.send(qa, thread_id, 'Two.')

        faculty = self.login(self.faculty)
        fresh = self.sync(faculty, thread=thread_id, after=first)['messages']
        self.assertEqual([m['body'] for m in fresh], ['Two.'])

    def test_unread_count_rises_for_someone_looking_elsewhere(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'One.')
        self.send(qa, thread_id, 'Two.')

        faculty = self.login(self.faculty)
        # No thread parameter: this is the poll every other page makes.
        self.assertEqual(self.sync(faculty, counts=1)['unread_messages'], 2)

    def test_viewing_a_thread_clears_its_unread(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'One.')

        faculty = self.login(self.faculty)
        self.sync(faculty, thread=thread_id, after=0)
        self.assertEqual(self.sync(faculty, counts=1)['unread_messages'], 0)

    def test_thread_previews_and_unread_come_back_in_the_list(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Latest line.')

        faculty = self.login(self.faculty)
        threads = self.sync(faculty)['threads']
        self.assertEqual(threads[0]['unread'], 1)
        self.assertEqual(threads[0]['preview'], 'Latest line.')

    def test_read_receipt_flips_once_the_other_side_looks(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Did you see this?')

        sent = self.sync(qa, thread=thread_id, after=0)['messages'][-1]
        self.assertFalse(sent['read'])

        self.login(self.faculty).get(f'/messages/threads/{thread_id}/')
        seen = self.sync(qa, thread=thread_id, after=0)['messages'][-1]
        self.assertTrue(seen['read'])

    def test_messages_carry_a_timestamp(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        message = self.send(qa, thread_id, 'Stamped.').json()['message']
        self.assertTrue(message['iso'])
        self.assertTrue(message['stamp'])
        self.assertRegex(message['time'], r'^\d{2}:\d{2}$')

    def test_first_unread_marks_where_to_draw_the_divider(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'One.')
        faculty = self.login(self.faculty)
        faculty.get(f'/messages/threads/{thread_id}/')      # reads up to here

        second = self.send(qa, thread_id, 'Two.').json()['message']['id']
        detail = faculty.get(f'/messages/threads/{thread_id}/').json()
        self.assertEqual(detail['first_unread'], second)

    def test_sync_never_leaks_another_persons_thread(self):
        qa = self.login(self.qa)
        thread_id = self.start_thread(qa, self.faculty)
        self.send(qa, thread_id, 'Private.')

        outsider = self.login(self.outsider)
        payload = self.sync(outsider, thread=thread_id, after=0)
        self.assertNotIn('messages', payload)
        self.assertEqual(payload['threads'], [])

    def test_anonymous_cannot_sync(self):
        self.assertEqual(self.client.get(reverse('messaging:sync')).status_code, 302)

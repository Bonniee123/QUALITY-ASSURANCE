"""
Sender identification.

Whether a message is "mine" is not a property of the message. It is a property
of the message *and* the account looking at it, so the same row must come back
sent for one participant and received for the other -- for every pair of
accounts, in both directions, with no special case for any role.
"""
import itertools
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from messaging.models import Thread, ThreadMessage


class SenderIdentityTests(TestCase):
    """Every account type, both directions."""

    def setUp(self):
        self.people = {}
        for username, role in (('s_admin', 'admin'), ('s_qa', 'qa_staff'),
                               ('s_fac', 'faculty'), ('s_fac2', 'faculty')):
            user = User.objects.create_user(username, f'{username}@e.com', 'testpass123')
            user.profile.role = role
            user.profile.save()
            self.people[username] = user

    def client_for(self, username):
        client = self.client_class()
        client.login(username=username, password='testpass123')
        return client

    def send(self, sender_name, other, body):
        client = self.client_for(sender_name)
        thread_id = client.post(
            reverse('messaging:thread_start'),
            json.dumps({'user_id': other.pk}), content_type='application/json',
        ).json()['thread']['id']
        client.post(f'/messages/threads/{thread_id}/send/',
                    json.dumps({'body': body}), content_type='application/json')
        return thread_id

    def messages_as(self, username, thread_id):
        return self.client_for(username).get(f'/messages/threads/{thread_id}/').json()['messages']

    def test_admin_to_qa_is_sent_for_admin_and_received_for_qa(self):
        thread = self.send('s_admin', self.people['s_qa'], 'Hello')

        admin_view = self.messages_as('s_admin', thread)[-1]
        qa_view = self.messages_as('s_qa', thread)[-1]

        self.assertEqual(admin_view['id'], qa_view['id'], 'same message row')
        self.assertTrue(admin_view['mine'], 'the sender must see it as sent')
        self.assertFalse(qa_view['mine'], 'the recipient must see it as received')

    def test_qa_to_admin_is_sent_for_qa_and_received_for_admin(self):
        thread = self.send('s_qa', self.people['s_admin'], 'Good morning')

        qa_view = self.messages_as('s_qa', thread)[-1]
        admin_view = self.messages_as('s_admin', thread)[-1]

        self.assertTrue(qa_view['mine'])
        self.assertFalse(admin_view['mine'])

    def test_mine_is_mirrored_for_every_pair_and_direction(self):
        """No role is special: the rule is the same for all of them."""
        for a, b in itertools.permutations(self.people, 2):
            with self.subTest(sender=a, recipient=b):
                thread = self.send(a, self.people[b], f'from {a} to {b}')
                sent = self.messages_as(a, thread)[-1]
                received = self.messages_as(b, thread)[-1]
                self.assertEqual(sent['id'], received['id'])
                self.assertTrue(sent['mine'])
                self.assertFalse(received['mine'])

    def test_every_message_carries_the_ids_the_decision_rests_on(self):
        thread = self.send('s_admin', self.people['s_qa'], 'Hello')
        admin = self.people['s_admin']

        for viewer, expected_viewer in (('s_admin', admin.pk),
                                        ('s_qa', self.people['s_qa'].pk)):
            row = self.messages_as(viewer, thread)[-1]
            self.assertEqual(row['sender_id'], admin.pk,
                             'sender_id must be the stored sender, not the viewer')
            self.assertEqual(row['viewer_id'], expected_viewer)
            self.assertEqual(row['mine'], row['sender_id'] == row['viewer_id'])

    def test_a_long_conversation_keeps_each_message_with_its_own_sender(self):
        thread = self.send('s_admin', self.people['s_qa'], 'one')
        qa = self.client_for('s_qa')
        admin = self.client_for('s_admin')
        for i, client in enumerate([qa, admin, qa, admin, qa]):
            client.post(f'/messages/threads/{thread}/send/',
                        json.dumps({'body': f'turn {i}'}), content_type='application/json')

        admin_view = self.messages_as('s_admin', thread)
        qa_view = self.messages_as('s_qa', thread)

        self.assertEqual(len(admin_view), len(qa_view))
        for a_row, q_row in zip(admin_view, qa_view):
            self.assertEqual(a_row['id'], q_row['id'])
            self.assertNotEqual(a_row['mine'], q_row['mine'],
                                f'message {a_row["id"]} was claimed by both sides')

    def test_existing_stored_messages_follow_their_stored_sender(self):
        """Rows written directly, not through the API, still resolve correctly."""
        admin, qa = self.people['s_admin'], self.people['s_qa']
        thread, _ = Thread.get_or_create_between(admin, qa)
        ThreadMessage.objects.create(thread=thread, sender=qa, body='historic')

        self.assertFalse(self.messages_as('s_admin', thread.pk)[-1]['mine'])
        self.assertTrue(self.messages_as('s_qa', thread.pk)[-1]['mine'])

    def test_sync_agrees_with_the_thread_view(self):
        """The polling path must not disagree with the initial render."""
        thread = self.send('s_admin', self.people['s_qa'], 'Hello')
        for username in ('s_admin', 's_qa'):
            client = self.client_for(username)
            detail = client.get(f'/messages/threads/{thread}/').json()['messages'][-1]
            synced = client.get(reverse('messaging:sync'),
                                {'thread': thread, 'after': 0}).json()['messages'][-1]
            self.assertEqual(detail['mine'], synced['mine'], f'{username}: paths disagree')
            self.assertEqual(detail['sender_id'], synced['sender_id'])


class MessagingCacheTests(TestCase):
    """
    These replies describe a thread *as seen by one account*, so they must never
    be stored by any cache. Django sets ``Vary: Cookie`` but no
    ``Cache-Control``, and a response with no freshness directive may be cached
    heuristically -- which is how a reply built for one signed-in user ends up
    replayed to the next, showing them someone else's messages as their own.
    """

    def setUp(self):
        self.user = User.objects.create_user('c_u', 'c@e.com', 'testpass123')
        self.other = User.objects.create_user('c_o', 'o@e.com', 'testpass123')
        self.thread, _ = Thread.get_or_create_between(self.user, self.other)
        ThreadMessage.objects.create(thread=self.thread, sender=self.other, body='hi')

    def test_per_user_endpoints_are_not_cacheable(self):
        client = self.client_class()
        client.login(username='c_u', password='testpass123')
        for path in (reverse('messaging:inbox'),
                     reverse('messaging:thread_list'),
                     reverse('messaging:people'),
                     reverse('messaging:sync'),
                     reverse('messaging:unread_count'),
                     f'/messages/threads/{self.thread.pk}/'):
            with self.subTest(path=path):
                cache_control = client.get(path).get('Cache-Control', '')
                self.assertIn('no-store', cache_control,
                              f'{path} may be cached and replayed to another account')

    def test_two_accounts_get_different_answers_for_the_same_thread(self):
        first = self.client_class()
        first.login(username='c_u', password='testpass123')
        second = self.client_class()
        second.login(username='c_o', password='testpass123')

        a = first.get(f'/messages/threads/{self.thread.pk}/').json()['messages'][-1]
        b = second.get(f'/messages/threads/{self.thread.pk}/').json()['messages'][-1]

        self.assertEqual(a['id'], b['id'])
        self.assertNotEqual(a['mine'], b['mine'])
        self.assertNotEqual(a['viewer_id'], b['viewer_id'])


class NoDuplicateThreadTests(TestCase):
    """
    One conversation per pair.

    Two threads between the same people put each side in a different room, so
    each saw only their own messages -- which reads exactly like the other
    person's messages being mislabelled.
    """

    def setUp(self):
        self.a = User.objects.create_user('d_a', 'a@e.com', 'testpass123')
        self.b = User.objects.create_user('d_b', 'b@e.com', 'testpass123')

    def test_starting_from_either_side_reuses_one_thread(self):
        first, created_first = Thread.get_or_create_between(self.a, self.b)
        second, created_second = Thread.get_or_create_between(self.b, self.a)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Thread.objects.count(), 1)

    def test_both_participants_see_the_same_messages(self):
        thread, _ = Thread.get_or_create_between(self.a, self.b)
        ThreadMessage.objects.create(thread=thread, sender=self.a, body='from a')
        ThreadMessage.objects.create(thread=thread, sender=self.b, body='from b')

        def ids_for(username):
            client = self.client_class()
            client.login(username=username, password='testpass123')
            return [m['id'] for m in
                    client.get(f'/messages/threads/{thread.pk}/').json()['messages']]

        self.assertEqual(ids_for('d_a'), ids_for('d_b'))

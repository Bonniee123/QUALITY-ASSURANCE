"""
"Read" means a person was there.

The Messages page refreshes the open conversation every few seconds and used to
mark every new message read the moment a refresh delivered it -- including
refreshes from a screen nobody was looking at. So a sender could be told "Read"
for up to an hour while the recipient was away from their desk.

Refreshes now say when nobody has touched the page for a minute. A passive
refresh still puts the message on screen but leaves it unread; the first
refresh after the reader is back marks what they now have in front of them.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

PASSWORD = 'testpass123'
PASSIVE = {'HTTP_X_QA_PASSIVE': '1'}


class PassiveRefreshReadReceiptTests(TestCase):

    def setUp(self):
        self.sender = User.objects.create_user('rr_sender', 's@e.com', PASSWORD)
        self.reader = User.objects.create_user('rr_reader', 'r@e.com', PASSWORD)
        self.sender_client = self.client_class()
        self.sender_client.login(username='rr_sender', password=PASSWORD)
        self.reader_client = self.client_class()
        self.reader_client.login(username='rr_reader', password=PASSWORD)

        self.thread = self.sender_client.post(
            reverse('messaging:thread_start'),
            json.dumps({'user_id': self.reader.pk}), content_type='application/json',
        ).json()['thread']['id']
        # The reader opens the conversation, so it is the one on their screen.
        self.reader_client.get(reverse('messaging:thread_detail', args=[self.thread]))

    def send(self, body):
        return self.sender_client.post(
            reverse('messaging:message_send', args=[self.thread]),
            json.dumps({'body': body}), content_type='application/json',
        ).json()['message']['id']

    def reader_refresh(self, after, passive):
        extra = PASSIVE if passive else {}
        return self.reader_client.get(
            reverse('messaging:sync'), {'thread': self.thread, 'after': after}, **extra,
        ).json()

    def sender_sees_read(self, message_id):
        """What the sender's own screen says about one of their messages."""
        rows = self.sender_client.get(
            reverse('messaging:thread_detail', args=[self.thread])).json()['messages']
        return [m for m in rows if m['id'] == message_id][0]['read']

    # ------------------------------------------------------------------ cases

    def test_nobody_at_the_page_the_message_arrives_but_stays_unread(self):
        sent = self.send('Are you there?')
        data = self.reader_refresh(after=0, passive=True)
        self.assertIn(sent, [m['id'] for m in data['messages']], 'still delivered to the screen')
        self.assertFalse(self.sender_sees_read(sent), 'the sender must not be told "Read"')
        self.assertEqual(data['unread_messages'], 1, 'and it still counts as unread')

    def test_someone_at_the_page_reads_it_as_before(self):
        sent = self.send('Good morning')
        self.reader_refresh(after=0, passive=False)
        self.assertTrue(self.sender_sees_read(sent))

    def test_coming_back_marks_what_arrived_while_away(self):
        """
        The message was already delivered by the passive refresh, so the next
        refresh brings nothing new -- and must still mark it read.
        """
        sent = self.send('Are you there?')
        delivered = self.reader_refresh(after=0, passive=True)
        last_seen = delivered['messages'][-1]['id']

        back = self.reader_refresh(after=last_seen, passive=False)
        self.assertEqual(back['messages'], [], 'nothing new arrived meanwhile')
        self.assertTrue(self.sender_sees_read(sent))
        self.assertEqual(back['unread_messages'], 0)

    def test_several_messages_while_away_are_all_read_on_return(self):
        ids = [self.send(f'message {n}') for n in range(3)]
        delivered = self.reader_refresh(after=0, passive=True)
        self.reader_refresh(after=delivered['messages'][-1]['id'], passive=False)
        self.assertTrue(all(self.sender_sees_read(i) for i in ids))

    def test_an_active_refresh_with_nothing_unread_writes_nothing(self):
        """No new messages and nothing unread: no read mark is written every tick."""
        from messaging.models import ThreadRead

        self.send('hello')
        delivered = self.reader_refresh(after=0, passive=False)
        last = delivered['messages'][-1]['id']
        before = ThreadRead.objects.get(thread_id=self.thread, user=self.reader).last_read_at
        self.reader_refresh(after=last, passive=False)
        after = ThreadRead.objects.get(thread_id=self.thread, user=self.reader).last_read_at
        self.assertEqual(before, after)

    def test_opening_the_conversation_still_reads_it(self):
        """Clicking into a conversation is the reader acting, passive or not."""
        sent = self.send('Are you there?')
        self.reader_refresh(after=0, passive=True)
        self.reader_client.get(reverse('messaging:thread_detail', args=[self.thread]))
        self.assertTrue(self.sender_sees_read(sent))

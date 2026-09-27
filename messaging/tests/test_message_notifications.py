"""
What the bell says when a message arrives.

It used to say the message. `_notify_recipients` put the first ninety
characters of the body into the notification, so a conversation could be read
without opening Messages, and every reply added another entry -- ten messages,
ten notifications, each carrying another slice of the exchange.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from messaging.models import Thread
from notifications.models import Notification


def make_user(username, role='qa_staff', first='', last=''):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!',
                                    first_name=first, last_name=last)
    user.profile.role = role
    user.profile.save()
    return user


class MessageNotificationTests(TestCase):

    def setUp(self):
        self.sender = make_user('note_sender', first='John', last='Doe')
        self.recipient = make_user('note_recipient', first='Mary', last='Cruz')
        self.thread = Thread.objects.create()
        self.thread.participants.add(self.sender, self.recipient)
        self.client.force_login(self.sender)

    def send(self, body):
        return self.client.post(reverse('messaging:message_send', args=[self.thread.pk]),
                                {'body': body}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def notification(self):
        return Notification.objects.filter(user=self.recipient, category='message').first()

    def test_the_notification_names_the_sender_and_not_the_message(self):
        secret = 'The budget figures for Area III are attached and confidential'
        self.send(secret)
        note = self.notification()
        self.assertIsNotNone(note)
        self.assertEqual(note.message, 'John Doe sent you a message.')
        self.assertNotIn('budget', note.message.lower())
        self.assertNotIn(secret[:20], note.message)

    def test_a_second_message_updates_the_same_notification(self):
        self.send('first')
        self.send('second')
        self.send('third')
        notes = Notification.objects.filter(user=self.recipient, category='message')
        self.assertEqual(notes.count(), 1, 'one conversation is one line in the bell')
        self.assertEqual(notes.first().message, 'John Doe sent you 3 messages.')

    def test_the_notification_links_to_the_conversation(self):
        self.send('hello')
        self.assertIn(f'thread={self.thread.pk}', self.notification().link)

    def test_a_read_notification_is_not_reused(self):
        """Once it has been seen, the next message deserves its own line."""
        self.send('first')
        Notification.objects.filter(user=self.recipient).update(is_read=True)
        self.send('second')
        self.assertEqual(Notification.objects.filter(user=self.recipient, category='message').count(), 2)

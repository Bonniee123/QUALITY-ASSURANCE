"""
Whose face appears beside a message.

The rule this file pins down: a message's picture is a property of the account
that sent it, and of nothing else. Not of the reader, not of the sender's role,
not of which side of the conversation is on screen. So the same message must
carry the *same* picture whoever opens it, while "mine vs theirs" -- the blue or
grey background -- keeps flipping per reader.

Those two facts pull in opposite directions, and that is exactly where a
messaging interface goes wrong, so the cases below check both at once.
"""
import itertools
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

# Smallest thing an ImageField will accept.
GIF = (b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00'
       b'\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;')

ROLES = (('a_admin', 'admin'), ('a_qa', 'qa_staff'),
         ('a_fac', 'faculty'), ('a_fac2', 'faculty'))


def make_person(username, role, with_photo=True):
    user = User.objects.create_user(username, username + '@e.com', 'testpass123',
                                    first_name=username.upper(), last_name='Tester')
    user.profile.role = role
    if with_photo:
        user.profile.avatar = SimpleUploadedFile(
            username + '.gif', GIF, content_type='image/gif')
    user.profile.save()
    return user


class MessageAvatarTests(TestCase):
    """Every account type, both directions."""

    def setUp(self):
        self.people = {name: make_person(name, role) for name, role in ROLES}

    # ---------------------------------------------------------------- helpers

    def client_for(self, username):
        client = self.client_class()
        client.login(username=username, password='testpass123')
        return client

    def start_thread(self, sender_name, other):
        return self.client_for(sender_name).post(
            reverse('messaging:thread_start'),
            json.dumps({'user_id': other.pk}),
            content_type='application/json',
        ).json()['thread']['id']

    def send(self, sender_name, thread_id, body):
        self.client_for(sender_name).post(
            reverse('messaging:message_send', args=[thread_id]),
            json.dumps({'body': body}), content_type='application/json')

    def messages_seen_by(self, reader_name, thread_id):
        response = self.client_for(reader_name).get(
            reverse('messaging:thread_detail', args=[thread_id]))
        return response.json()['messages']

    def photo_of(self, username):
        return self.people[username].profile.avatar_url

    # ------------------------------------------------------------------ cases

    def test_each_bubble_carries_its_own_senders_photo(self):
        """
        The worked example from the request: the admin says hello, QA replies,
        and each line keeps its author's face for both readers.
        """
        thread = self.start_thread('a_admin', self.people['a_qa'])
        self.send('a_admin', thread, 'Hello')
        self.send('a_qa', thread, 'Good morning')

        for reader in ('a_admin', 'a_qa'):
            rows = {m['body']: m for m in self.messages_seen_by(reader, thread)}
            self.assertEqual(rows['Hello']['avatar'], self.photo_of('a_admin'),
                             reader + ' sees the wrong face on the admin message')
            self.assertEqual(rows['Good morning']['avatar'], self.photo_of('a_qa'),
                             reader + ' sees the wrong face on the QA message')

    def test_a_message_looks_the_same_to_everyone_who_can_read_it(self):
        """The picture does not change when the reader changes."""
        thread = self.start_thread('a_admin', self.people['a_qa'])
        self.send('a_admin', thread, 'Hello')

        as_sender = self.messages_seen_by('a_admin', thread)[0]
        as_recipient = self.messages_seen_by('a_qa', thread)[0]

        self.assertEqual(as_sender['avatar'], as_recipient['avatar'])
        # ... while the side it lands on still flips. Both have to hold.
        self.assertTrue(as_sender['mine'])
        self.assertFalse(as_recipient['mine'])

    def test_the_readers_own_photo_never_lands_on_someone_elses_message(self):
        """
        The specific failure being guarded against: one face stamped down the
        whole conversation.
        """
        names = [name for name, _ in ROLES]
        for sender, reader in itertools.permutations(names, 2):
            with self.subTest(sender=sender, reader=reader):
                thread = self.start_thread(sender, self.people[reader])
                self.send(sender, thread, 'ping')
                # The reverse direction of each pair reuses the same thread, so
                # the message just sent is the last one, not the first.
                row = self.messages_seen_by(reader, thread)[-1]
                self.assertEqual(row['avatar'], self.photo_of(sender))
                self.assertNotEqual(row['avatar'], self.photo_of(reader))

    def test_two_faculty_accounts_do_not_share_a_face(self):
        """Same role, different people -- the picture must still tell them apart."""
        thread = self.start_thread('a_fac', self.people['a_fac2'])
        self.send('a_fac', thread, 'from one')
        self.send('a_fac2', thread, 'from the other')

        rows = {m['body']: m['avatar'] for m in self.messages_seen_by('a_fac', thread)}
        self.assertEqual(rows['from one'], self.photo_of('a_fac'))
        self.assertEqual(rows['from the other'], self.photo_of('a_fac2'))
        self.assertNotEqual(rows['from one'], rows['from the other'])

    def test_the_photo_agrees_with_the_sender_id(self):
        """
        Photo and sender have to point at the same account. If they ever
        disagree, the interface is labelling one person's words with another
        person's face.
        """
        thread = self.start_thread('a_qa', self.people['a_fac'])
        self.send('a_qa', thread, 'one')
        self.send('a_fac', thread, 'two')

        for row in self.messages_seen_by('a_fac', thread):
            expected = User.objects.get(pk=row['sender_id']).profile.avatar_url
            self.assertEqual(row['avatar'], expected)

    def test_a_sender_with_no_photo_falls_back_instead_of_breaking(self):
        make_person('a_bare', 'faculty', with_photo=False)
        thread = self.start_thread('a_bare', self.people['a_admin'])
        self.send('a_bare', thread, 'no picture here')

        row = self.messages_seen_by('a_admin', thread)[0]
        self.assertEqual(row['avatar'], '')
        # The initials still identify the sender, so nothing is left blank.
        self.assertEqual(row['initials'], 'AT')

    def test_new_messages_arriving_through_sync_carry_the_same_photo(self):
        """The live poll builds its own payloads; they must not drift."""
        thread = self.start_thread('a_admin', self.people['a_qa'])
        self.send('a_admin', thread, 'first')

        payload = self.client_for('a_qa').get(
            reverse('messaging:sync'), {'thread': thread, 'after': 0}).json()
        rows = payload.get('messages') or []
        self.assertTrue(rows, 'sync returned no messages to check')
        self.assertEqual(rows[0]['avatar'], self.photo_of('a_admin'))


class RosterAvatarTests(TestCase):
    """The conversation list and the people picker show each person's own face."""

    def setUp(self):
        self.people = {name: make_person(name, role) for name, role in ROLES[:3]}

    def client_for(self, username):
        client = self.client_class()
        client.login(username=username, password='testpass123')
        return client

    def test_people_picker_gives_every_row_its_own_photo(self):
        rows = self.client_for('a_admin').get(reverse('messaging:people')).json()['people']
        self.assertTrue(rows)
        for row in rows:
            expected = User.objects.get(pk=row['id']).profile.avatar_url
            self.assertEqual(row['avatar'], expected)

    def test_thread_row_shows_the_other_person_not_the_reader(self):
        client = self.client_for('a_admin')
        client.post(reverse('messaging:thread_start'),
                    json.dumps({'user_id': self.people['a_qa'].pk}),
                    content_type='application/json')

        rows = client.get(reverse('messaging:thread_list')).json()['threads']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['avatar'], self.people['a_qa'].profile.avatar_url)
        self.assertNotEqual(rows[0]['avatar'], self.people['a_admin'].profile.avatar_url)

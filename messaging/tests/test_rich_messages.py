"""
Attachments, voice messages, replies, reactions, typing, retried sends, and the
change-based sync that keeps two open conversations identical.
"""
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from documents.models import ActivityLog
from messaging.models import MessageAttachment, MessageReaction, Thread, ThreadMessage
from notifications.models import Notification

MEDIA = tempfile.mkdtemp()
PASSWORD = 'pass12345'


def account(name, role='faculty'):
    user = User.objects.create_user(name, f'{name}@test.com', PASSWORD, first_name=name.title())
    user.profile.role = role
    user.profile.save()
    return user


def png(name='photo.png', size=(64, 48), color=(20, 120, 150)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def pdf(name='report.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n', content_type='application/pdf')


def webm(name='voice.webm'):
    return SimpleUploadedFile(name, b'\x1a\x45\xdf\xa3' + b'\x00' * 400, content_type='audio/webm')


@override_settings(MEDIA_ROOT=MEDIA)
class RichMessageTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.qa = account('rich_qa', 'qa_staff')
        self.fac = account('rich_fac')
        self.outsider = account('rich_out')
        self.thread, _ = Thread.get_or_create_between(self.qa, self.fac)

    def send(self, user, **data):
        self.client.force_login(user)
        url = reverse('messaging:message_send', args=[self.thread.pk])
        if any(isinstance(v, (SimpleUploadedFile, list)) for v in data.values()):
            return self.client.post(url, data)
        import json
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def sync(self, user, seq, **extra):
        self.client.force_login(user)
        return self.client.get(reverse('messaging:sync'), {'thread': self.thread.pk, 'seq': seq, **extra}).json()

    # ------------------------------------------------------------- retries

    def test_a_retried_send_does_not_send_twice(self):
        first = self.send(self.qa, body='Hello', client_id='c-123').json()
        again = self.send(self.qa, body='Hello', client_id='c-123').json()
        self.assertEqual(first['message']['id'], again['message']['id'])
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(ThreadMessage.objects.filter(thread=self.thread).count(), 1)
        self.assertEqual(first['message']['client_id'], 'c-123')

    def test_a_client_id_cannot_be_replayed_into_another_conversation(self):
        self.send(self.qa, body='Hello', client_id='c-xyz')
        other, _ = Thread.get_or_create_between(self.qa, self.outsider)
        self.client.force_login(self.qa)
        import json
        r = self.client.post(reverse('messaging:message_send', args=[other.pk]),
                             json.dumps({'body': 'x', 'client_id': 'c-xyz'}), content_type='application/json')
        self.assertEqual(r.status_code, 409)

    # ------------------------------------------------------------- replies

    def test_a_reply_quotes_the_message_it_answers(self):
        original = self.send(self.fac, body='Which file?').json()['message']
        reply = self.send(self.qa, body='The PDF.', reply_to=original['id']).json()['message']
        self.assertEqual(reply['reply_to']['id'], original['id'])
        self.assertEqual(reply['reply_to']['snippet'], 'Which file?')
        self.assertEqual(reply['reply_to']['sender'], 'Rich_Fac')

    def test_a_reply_to_another_conversations_message_is_refused(self):
        other, _ = Thread.get_or_create_between(self.qa, self.outsider)
        foreign = ThreadMessage.objects.create(thread=other, sender=self.outsider, body='secret')
        r = self.send(self.qa, body='x', reply_to=foreign.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'reply_gone')

    def test_a_reply_to_a_deleted_message_says_so(self):
        original = self.send(self.fac, body='oops').json()['message']
        reply = self.send(self.qa, body='?', reply_to=original['id']).json()['message']
        self.client.force_login(self.fac)
        self.client.post(reverse('messaging:message_delete', args=[self.thread.pk, original['id']]))
        self.client.force_login(self.qa)
        msgs = self.client.get(reverse('messaging:thread_detail', args=[self.thread.pk])).json()['messages']
        quoted = next(m for m in msgs if m['id'] == reply['id'])['reply_to']
        self.assertTrue(quoted['deleted'])
        self.assertEqual(quoted['snippet'], '')

    # --------------------------------------------------------- attachments

    def test_a_picture_is_stored_with_a_thumbnail_and_shown_to_both(self):
        r = self.send(self.qa, body='', files=[png()]).json()
        att = r['message']['attachments'][0]
        self.assertEqual((att['kind'], att['type'], att['width'], att['height']), ('image', 'image/png', 64, 48))
        self.assertTrue(MessageAttachment.objects.get(pk=att['id']).thumbnail)
        for user in (self.qa, self.fac):
            self.client.force_login(user)
            served = self.client.get(att['url'])
            self.assertEqual(served.status_code, 200)
            self.assertEqual(served['Content-Type'], 'image/png')
            self.assertIn('inline', served['Content-Disposition'])
            self.assertIn('sandbox', served['Content-Security-Policy'])
            self.assertEqual(self.client.get(att['thumb_url']).status_code, 200)

    def test_nobody_else_can_open_an_attachment(self):
        att = self.send(self.qa, files=[png()]).json()['message']['attachments'][0]
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(att['url']).status_code, 404)
        self.client.logout()
        self.assertNotEqual(self.client.get(att['url']).status_code, 200)

    def test_files_are_downloads_and_typed_by_the_server(self):
        att = self.send(self.qa, files=[pdf()]).json()['message']['attachments'][0]
        self.assertEqual(att['kind'], 'file')
        self.client.force_login(self.fac)
        served = self.client.get(att['url'])
        self.assertIn('attachment', served['Content-Disposition'])
        self.assertEqual(served['Content-Type'], 'application/pdf')

    def test_a_program_renamed_to_a_picture_is_refused(self):
        fake = SimpleUploadedFile('cat.png', b'MZ\x90\x00' + b'\x00' * 200, content_type='image/png')
        r = self.send(self.qa, files=[fake])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'invalid_type')
        self.assertFalse(ThreadMessage.objects.filter(thread=self.thread).exists())

    def test_types_never_accepted_are_refused(self):
        for upload in (SimpleUploadedFile('page.html', b'<script>x</script>', content_type='text/html'),
                       SimpleUploadedFile('run.exe', b'MZ' + b'\x00' * 50, content_type='application/octet-stream'),
                       SimpleUploadedFile('pic.svg', b'<svg/>', content_type='image/svg+xml')):
            with self.subTest(name=upload.name):
                r = self.send(self.qa, files=[upload])
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()['code'], 'invalid_type')

    @override_settings(MESSAGE_ATTACHMENT_MAX_MB=1)
    def test_a_file_over_the_limit_is_refused_by_name(self):
        big = SimpleUploadedFile('big.pdf', b'%PDF-1.4\n' + b'0' * (1024 * 1024 + 10), content_type='application/pdf')
        r = self.send(self.qa, files=[big]).json()
        self.assertEqual(r['code'], 'too_large')
        self.assertIn('big.pdf', r['error'])

    @override_settings(MESSAGE_ATTACHMENTS_PER_MESSAGE=2)
    def test_too_many_files_at_once_is_refused(self):
        r = self.send(self.qa, files=[png('a.png'), png('b.png'), png('c.png')])
        self.assertEqual(r.json()['code'], 'too_many')

    def test_one_bad_file_sends_nothing(self):
        bad = SimpleUploadedFile('x.png', b'not a picture', content_type='image/png')
        self.send(self.qa, body='with files', files=[png(), bad])
        self.assertFalse(ThreadMessage.objects.filter(thread=self.thread).exists())
        self.assertFalse(MessageAttachment.objects.exists())

    def test_a_deleted_messages_files_are_no_longer_served(self):
        sent = self.send(self.qa, files=[png()]).json()['message']
        self.client.post(reverse('messaging:message_delete', args=[self.thread.pk, sent['id']]))
        self.client.force_login(self.fac)
        self.assertEqual(self.client.get(sent['attachments'][0]['url']).status_code, 404)

    def test_voice_messages(self):
        r = self.send(self.qa, voice=webm(), voice_duration='12.4').json()
        att = r['message']['attachments'][0]
        self.assertEqual((att['kind'], att['type'], att['duration']), ('voice', 'audio/webm', 12.4))
        self.assertTrue(att['name'].startswith('Voice message'))
        bad = self.send(self.qa, voice=SimpleUploadedFile('v.webm', b'hello', content_type='audio/webm'))
        self.assertEqual(bad.json()['code'], 'invalid_type')

    def test_notifications_and_previews_say_what_was_sent(self):
        self.send(self.qa, files=[png()])
        note = Notification.objects.get(user=self.fac, category='message')
        self.assertEqual(note.message, 'Rich_Qa sent you a photo.')
        self.client.force_login(self.fac)
        rows = self.client.get(reverse('messaging:thread_list')).json()['threads']
        self.assertEqual(rows[0]['preview'], 'A photo')
        self.client.force_login(self.qa)
        rows = self.client.get(reverse('messaging:thread_list')).json()['threads']
        self.assertEqual(rows[0]['preview'], 'You: Sent a photo')

    def test_sending_files_is_recorded_without_content(self):
        self.send(self.qa, body='private words', files=[pdf()])
        entry = ActivityLog.objects.filter(action='send_message').latest('pk')
        self.assertIn('1 attachment', entry.description)
        self.assertNotIn('private words', entry.description)
        self.assertNotIn('report.pdf', entry.description)

    # ----------------------------------------------------------- reactions

    def react(self, user, message_id, emoji):
        self.client.force_login(user)
        import json
        return self.client.post(reverse('messaging:message_react', args=[self.thread.pk, message_id]),
                                json.dumps({'emoji': emoji}), content_type='application/json')

    def test_reactions_toggle_and_say_who(self):
        mid = self.send(self.fac, body='Done!').json()['message']['id']
        r = self.react(self.qa, mid, '👍').json()['message']['reactions']
        self.assertEqual(r, [{'emoji': '👍', 'count': 1, 'mine': True, 'names': ['You']}])
        self.react(self.fac, mid, '👍')
        self.client.force_login(self.fac)
        msgs = self.client.get(reverse('messaging:thread_detail', args=[self.thread.pk])).json()['messages']
        self.assertEqual(msgs[0]['reactions'][0]['count'], 2)
        self.assertEqual(sorted(msgs[0]['reactions'][0]['names']), ['Rich_Qa', 'You'])
        self.react(self.qa, mid, '👍')  # take it back
        self.assertEqual(MessageReaction.objects.filter(message_id=mid).count(), 1)

    def test_only_offered_reactions_and_only_participants(self):
        mid = self.send(self.fac, body='x').json()['message']['id']
        self.assertEqual(self.react(self.qa, mid, '<b>').status_code, 400)
        self.assertEqual(self.react(self.outsider, mid, '👍').status_code, 404)

    # -------------------------------------------------- sync and typing

    def test_the_sync_delivers_every_change_once_in_order(self):
        self.client.force_login(self.fac)
        start = self.client.get(reverse('messaging:thread_detail', args=[self.thread.pk])).json()['seq']
        a = self.send(self.qa, body='one').json()['message']['id']
        b = self.send(self.qa, body='two').json()['message']['id']
        first = self.sync(self.fac, start)
        self.assertEqual([c['id'] for c in first['changes']], [a, b])
        self.react(self.fac, a, '❤️')
        self.client.force_login(self.qa)
        self.client.post(reverse('messaging:message_delete', args=[self.thread.pk, b]))
        second = self.sync(self.fac, first['seq'])
        self.assertEqual([(c['id'], c.get('deleted', False)) for c in second['changes']], [(a, False), (b, True)])
        self.assertEqual(second['changes'][0]['reactions'][0]['emoji'], '❤️')
        self.assertEqual(self.sync(self.fac, second['seq'])['changes'], [])

    def test_typing_shows_to_the_other_person_and_stops(self):
        self.client.force_login(self.qa)
        import json
        url = reverse('messaging:typing', args=[self.thread.pk])
        self.client.post(url, json.dumps({'typing': True}), content_type='application/json')
        self.assertEqual(self.sync(self.fac, 0)['typing'], ['Rich_Qa'])
        self.assertEqual(self.sync(self.qa, 0)['typing'], [], 'nobody is shown their own typing')
        self.client.force_login(self.qa)
        self.client.post(url, json.dumps({'typing': False}), content_type='application/json')
        self.assertEqual(self.sync(self.fac, 0)['typing'], [])

    def test_typing_needs_a_participant(self):
        self.client.force_login(self.outsider)
        r = self.client.post(reverse('messaging:typing', args=[self.thread.pk]), '{}', content_type='application/json')
        self.assertEqual(r.status_code, 404)


@override_settings(MEDIA_ROOT=MEDIA)
class AttachmentCleanupTests(TestCase):
    """No file is left on disk without a row that refers to it."""

    def test_files_go_when_the_conversation_goes(self):
        import os
        qa, fac = account('clean_qa', 'qa_staff'), account('clean_fac')
        thread, _ = Thread.get_or_create_between(qa, fac)
        self.client.force_login(qa)
        r = self.client.post(reverse('messaging:message_send', args=[thread.pk]), {'files': [png(), pdf()]}).json()
        paths = []
        for a in MessageAttachment.objects.filter(message_id=r['message']['id']):
            paths.append(a.file.path)
            if a.thumbnail:
                paths.append(a.thumbnail.path)
        self.assertTrue(paths and all(os.path.exists(p) for p in paths))
        fac.delete()   # the conversation is removed with the account
        self.assertFalse(any(os.path.exists(p) for p in paths), 'attachment files were left behind')

    def test_a_message_hidden_by_its_sender_keeps_its_file(self):
        import os
        qa, fac = account('keep_qa', 'qa_staff'), account('keep_fac')
        thread, _ = Thread.get_or_create_between(qa, fac)
        self.client.force_login(qa)
        sent = self.client.post(reverse('messaging:message_send', args=[thread.pk]), {'files': [pdf()]}).json()['message']
        path = MessageAttachment.objects.get(pk=sent['attachments'][0]['id']).file.path
        self.client.post(reverse('messaging:message_delete', args=[thread.pk, sent['id']]))
        self.assertTrue(os.path.exists(path), 'a deleted message is hidden, not erased')

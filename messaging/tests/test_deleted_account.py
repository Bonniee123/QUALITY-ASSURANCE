"""
Deleting an account removes its conversations from everyone's Messages.

It used to leave each one behind with a single participant, shown to the
other person as a "Deleted user" row that led nowhere.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from messaging.models import Thread, ThreadMessage
from notifications.models import Notification

PASSWORD = 'pass12345'


def account(name, role):
    user = User.objects.create_user(name, f'{name}@test.com', PASSWORD)
    user.profile.role = role
    user.profile.save()
    return user


class DeletedAccountConversationTests(TestCase):

    def setUp(self):
        self.admin = account('del_conv_admin', 'admin')
        self.qa = account('del_conv_qa', 'qa_staff')
        self.leaving = account('del_conv_leaving', 'faculty')
        self.staying = account('del_conv_staying', 'faculty')
        self.gone_thread, _ = Thread.get_or_create_between(self.qa, self.leaving)
        ThreadMessage.objects.create(thread=self.gone_thread, sender=self.leaving, body='hello')
        Notification.objects.create(user=self.qa, message='New message', category='message',
                                    link=f"{reverse('messaging:inbox')}?thread={self.gone_thread.pk}")
        self.kept_thread, _ = Thread.get_or_create_between(self.qa, self.staying)
        ThreadMessage.objects.create(thread=self.kept_thread, sender=self.staying, body='still here')

    def delete_via_user_management(self, user):
        self.client.force_login(self.admin)
        return self.client.post(reverse('accounts:user_delete', args=[user.pk]))

    def test_the_conversation_disappears_from_the_other_persons_list(self):
        self.delete_via_user_management(self.leaving)
        self.client.force_login(self.qa)
        threads = self.client.get(reverse('messaging:sync')).json()['threads']
        self.assertEqual([t['id'] for t in threads], [self.kept_thread.pk])
        self.assertNotIn('Deleted user', [t['name'] for t in threads])

    def test_its_messages_and_notifications_go_too(self):
        gone = self.gone_thread.pk
        self.delete_via_user_management(self.leaving)
        self.assertFalse(Thread.objects.filter(pk=gone).exists())
        self.assertFalse(ThreadMessage.objects.filter(thread_id=gone).exists())
        self.assertFalse(Notification.objects.filter(link__endswith=f'?thread={gone}').exists())

    def test_other_conversations_are_untouched(self):
        self.delete_via_user_management(self.leaving)
        self.assertTrue(ThreadMessage.objects.filter(thread=self.kept_thread, body='still here').exists())

    def test_any_way_of_deleting_the_account_does_it(self):
        self.leaving.delete()
        self.assertFalse(Thread.objects.filter(pk=self.gone_thread.pk).exists())

    def test_an_open_conversation_is_told_it_is_gone(self):
        gone = self.gone_thread.pk
        self.delete_via_user_management(self.leaving)
        self.client.force_login(self.qa)
        body = self.client.get(reverse('messaging:sync'), {'thread': gone}).json()
        self.assertTrue(body.get('thread_gone'))

    def test_conversations_left_behind_earlier_are_cleaned_up_by_the_migration(self):
        """The rows already showing "Deleted user" before this fix."""
        import importlib
        from django.apps import apps as django_apps

        orphan = Thread.objects.create()
        orphan.participants.add(self.qa)
        ThreadMessage.objects.create(thread=orphan, sender=None, body='from a deleted account')
        migration = importlib.import_module('messaging.migrations.0003_remove_orphaned_threads')
        migration.remove_orphans(django_apps, None)
        self.assertFalse(Thread.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(Thread.objects.filter(pk=self.kept_thread.pk).exists())

"""
An Administrator cannot lock themselves out of their own account.

Before this, an Administrator could delete, deactivate or demote their own
account from User Management, and nothing kept the last active Administrator in
place; deleting yourself also ended in a server error.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import ActivityLog


def make_user(username, role, **extra):
    user = User.objects.create_user(username, f'{username}@example.com', 'pass12345', **extra)
    user.first_name, user.last_name = 'Test', 'User'
    user.save()
    user.profile.role = role
    user.profile.save()
    return user


def edit_data(user, **changes):
    data = {
        'username': user.username, 'email': user.email, 'first_name': user.first_name,
        'last_name': user.last_name, 'is_active': 'on', 'role': user.profile.role,
        'department': '', 'status': 'active', 'phone': '',
    }
    data.update(changes)
    return {k: v for k, v in data.items() if v is not None}


class SelfProtectionTests(TestCase):

    def setUp(self):
        self.admin = make_user('qatest_admin', 'admin')
        self.other = make_user('qatest_other', 'qa_staff')
        self.client.force_login(self.admin)

    def test_deleting_yourself_is_refused_with_a_message(self):
        response = self.client.post(reverse('accounts:user_delete', args=[self.admin.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertContains(response, 'You cannot delete your own account.')

    def test_the_delete_page_is_not_offered_for_yourself(self):
        response = self.client.get(reverse('accounts:user_delete', args=[self.admin.pk]))
        self.assertRedirects(response, reverse('accounts:user_detail', args=[self.admin.pk]))

    def test_deleting_someone_else_still_works_and_is_logged(self):
        response = self.client.post(reverse('accounts:user_delete', args=[self.other.pk]))
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.assertFalse(User.objects.filter(pk=self.other.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='delete_user', user=self.admin).exists())

    def test_demoting_yourself_is_refused(self):
        response = self.client.post(reverse('accounts:user_edit', args=[self.admin.pk]),
                                    edit_data(self.admin, role='qa_staff'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You cannot remove your own Administrator role.')
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.role, 'admin')

    def test_deactivating_yourself_is_refused(self):
        response = self.client.post(reverse('accounts:user_edit', args=[self.admin.pk]),
                                    edit_data(self.admin, status='inactive'))
        self.assertContains(response, 'You cannot deactivate your own account.')
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.status, 'active')

    def test_turning_off_your_own_sign_in_is_refused(self):
        response = self.client.post(reverse('accounts:user_edit', args=[self.admin.pk]),
                                    edit_data(self.admin, is_active=None))
        self.assertContains(response, 'You cannot turn off sign-in for your own account.')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_editing_your_own_details_still_works(self):
        response = self.client.post(reverse('accounts:user_edit', args=[self.admin.pk]),
                                    edit_data(self.admin, first_name='Renamed'))
        self.assertRedirects(response, reverse('accounts:user_detail', args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, 'Renamed')

    def test_you_can_still_demote_and_deactivate_someone_else(self):
        second_admin = make_user('qatest_admin2', 'admin')
        response = self.client.post(reverse('accounts:user_edit', args=[second_admin.pk]),
                                    edit_data(second_admin, role='qa_staff', status='inactive'))
        self.assertRedirects(response, reverse('accounts:user_detail', args=[second_admin.pk]))
        second_admin.profile.refresh_from_db()
        self.assertEqual((second_admin.profile.role, second_admin.profile.status), ('qa_staff', 'inactive'))

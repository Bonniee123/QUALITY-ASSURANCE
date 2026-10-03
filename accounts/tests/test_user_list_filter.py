"""
Filtering User Management by role (S-ADMIN-04).

The page listed every account in one table with no way to narrow it, so finding
the Faculty accounts meant reading every row.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class UserListRoleFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        def user(name, role):
            account = User.objects.create_user(name, f'{name}@test.com', 'pass12345')
            account.profile.role = role
            account.profile.save()
            return account

        cls.admin = user('filter_admin', 'admin')
        cls.qa_one = user('filter_qa_one', 'qa_staff')
        cls.qa_two = user('filter_qa_two', 'qa_staff')
        cls.faculty = user('filter_faculty', 'faculty')
        cls.url = reverse('accounts:user_list')

    def setUp(self):
        self.client.force_login(self.admin)

    def listed(self, response):
        return {u.username for u in response.context['users']}

    def test_no_filter_lists_everybody(self):
        self.assertEqual(
            self.listed(self.client.get(self.url)),
            {'filter_admin', 'filter_qa_one', 'filter_qa_two', 'filter_faculty'},
        )

    def test_admin_filter(self):
        self.assertEqual(self.listed(self.client.get(self.url, {'role': 'admin'})), {'filter_admin'})

    def test_qa_head_filter(self):
        self.assertEqual(
            self.listed(self.client.get(self.url, {'role': 'qa_staff'})),
            {'filter_qa_one', 'filter_qa_two'},
        )

    def test_faculty_filter(self):
        self.assertEqual(
            self.listed(self.client.get(self.url, {'role': 'faculty'})), {'filter_faculty'})

    def test_each_chip_carries_its_count(self):
        counts = {f['value']: f['count'] for f in self.client.get(self.url).context['role_filters']}
        self.assertEqual(counts[''], 4)
        self.assertEqual(counts['admin'], 1)
        self.assertEqual(counts['qa_staff'], 2)
        self.assertEqual(counts['faculty'], 1)

    def test_the_selected_chip_is_marked(self):
        response = self.client.get(self.url, {'role': 'faculty'})
        self.assertEqual(response.context['selected_role'], 'faculty')
        self.assertContains(response, 'aria-current="page"')

    def test_an_unknown_role_shows_everybody(self):
        """
        A hand-edited or stale ?role= must not empty the table.

        Filtering on it directly would return nothing, which reads as "the
        accounts are gone" rather than "that is not a role".
        """
        response = self.client.get(self.url, {'role': 'superuser'})
        self.assertEqual(response.context['selected_role'], '')
        self.assertEqual(len(self.listed(response)), 4)

    def test_an_empty_role_shows_everybody(self):
        self.assertEqual(len(self.listed(self.client.get(self.url, {'role': ''}))), 4)

    def test_a_role_nobody_holds_says_so_and_offers_a_way_back(self):
        User.objects.filter(username='filter_faculty').delete()
        response = self.client.get(self.url, {'role': 'faculty'})
        self.assertEqual(len(self.listed(response)), 0)
        self.assertContains(response, 'No users with this role')
        self.assertContains(response, 'Show all users')
        self.assertNotContains(response, 'Create the first user account')

    def test_filtering_keeps_deactivated_accounts_last(self):
        """The page's ordering is not lost when a role is chosen."""
        self.qa_one.profile.status = 'inactive'
        self.qa_one.profile.save()
        listed = [u.username for u in
                  self.client.get(self.url, {'role': 'qa_staff'}).context['users']]
        self.assertEqual(listed[-1], 'filter_qa_one')

    def test_a_non_admin_cannot_reach_the_page_at_all(self):
        self.client.force_login(self.faculty)
        response = self.client.get(self.url, {'role': 'admin'})
        self.assertNotEqual(response.status_code, 200)

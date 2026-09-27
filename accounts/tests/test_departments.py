"""
Tests for managing the department list.

The dropdown on the account forms used to be a constant in the code, so adding
an office meant a code change. These tests cover the replacement: the list is
data, an Administrator alone may change it, and changing it never disturbs the
accounts that already record a department.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.forms import UserCreateForm, UserEditForm, department_choices
from accounts.models import Department


def make_user(username, role, password='Str0ng-Passw0rd!'):
    user = User.objects.create_user(username=username, password=password)
    user.profile.role = role
    user.profile.save()
    return user


class DepartmentAccessTests(TestCase):
    """Only an Administrator may manage the list."""

    def setUp(self):
        self.admin = make_user('dept_admin', 'admin')
        self.qa = make_user('dept_qa', 'qa_staff')
        self.faculty = make_user('dept_faculty', 'faculty')
        self.department = Department.objects.create(name='Registrar')

    def test_admin_can_read_the_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('accounts:department_quick_list'))
        self.assertEqual(response.status_code, 200)
        names = [row['name'] for row in response.json()['departments']]
        self.assertIn('Registrar', names)

    def test_list_reports_the_account_count(self):
        member = make_user('counted_member', 'faculty')
        member.profile.department = 'Registrar'
        member.profile.save()
        self.client.force_login(self.admin)
        rows = self.client.get(reverse('accounts:department_quick_list')).json()['departments']
        row = next(r for r in rows if r['name'] == 'Registrar')
        self.assertEqual(row['members'], 1)

    def test_qa_head_and_faculty_are_refused(self):
        for user in (self.qa, self.faculty):
            self.client.force_login(user)
            response = self.client.get(reverse('accounts:department_quick_list'))
            self.assertNotEqual(response.status_code, 200)

    def test_anonymous_is_refused(self):
        response = self.client.get(reverse('accounts:department_quick_list'))
        self.assertNotEqual(response.status_code, 200)


class DepartmentDropdownTests(TestCase):
    """What the account forms offer follows the table."""

    def setUp(self):
        self.admin = make_user('drop_admin', 'admin')

    def test_added_department_appears_in_the_dropdown(self):
        self.assertNotIn('Registrar', dict(department_choices()))
        Department.objects.create(name='Registrar')
        self.assertIn('Registrar', dict(department_choices()))
        self.assertIn('Registrar', dict(UserCreateForm().fields['department'].choices))

    def test_inactive_department_is_not_offered(self):
        Department.objects.create(name='Retired Office', is_active=False)
        self.assertNotIn('Retired Office', dict(department_choices()))

    def test_blank_choice_is_always_first(self):
        Department.objects.create(name='Registrar')
        self.assertEqual(department_choices()[0][0], '')


class DepartmentDataSafetyTests(TestCase):
    """Changing the list never disturbs accounts that record a department."""

    def setUp(self):
        self.admin = make_user('safe_admin', 'admin')
        self.member = make_user('safe_member', 'faculty')
        self.member.profile.department = 'Registrar'
        self.member.profile.save()
        self.department = Department.objects.create(name='Registrar')

    def test_member_count_reports_accounts_holding_the_name(self):
        self.assertEqual(self.department.member_count, 1)

    def test_deleting_a_department_leaves_the_account_untouched(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('accounts:department_quick_delete', args=[self.department.pk]))
        self.assertFalse(Department.objects.filter(name='Registrar').exists())
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.department, 'Registrar')
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())

    def test_edit_form_still_offers_a_department_no_longer_listed(self):
        """An account keeps its department even after the row is removed."""
        self.department.delete()
        form = UserEditForm(instance=self.member)
        self.assertIn('Registrar', dict(form.fields['department'].choices))


class DepartmentValidationTests(TestCase):
    """Names stay unique whatever their casing."""

    def setUp(self):
        self.admin = make_user('valid_admin', 'admin')
        self.client.force_login(self.admin)
        # The seed migration already creates "QA Office", so ask for it rather
        # than creating it again.
        Department.objects.get_or_create(name='QA Office')
        self.before = Department.objects.count()

    def test_duplicate_name_in_another_casing_makes_no_second_row(self):
        response = self.client.post(reverse('accounts:department_quick_add'),
                                    {'name': 'qa office'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Department.objects.filter(name__iexact='qa office').count(), 1)

    def test_blank_name_is_refused(self):
        response = self.client.post(reverse('accounts:department_quick_add'), {'name': '   '})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Department.objects.count(), self.before)

    def test_creating_a_department_records_an_activity_log(self):
        from documents.models import ActivityLog

        self.client.post(reverse('accounts:department_quick_add'), {'name': 'Library'})
        self.assertTrue(Department.objects.filter(name='Library').exists())
        self.assertTrue(ActivityLog.objects.filter(action='create_department').exists())

    def test_removing_a_department_records_an_activity_log(self):
        from documents.models import ActivityLog

        dept = Department.objects.create(name='Temporary Office')
        self.client.post(reverse('accounts:department_quick_delete', args=[dept.pk]))
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='delete_department').exists())

    def test_removing_needs_a_post(self):
        dept = Department.objects.create(name='Temporary Office')
        response = self.client.get(reverse('accounts:department_quick_delete', args=[dept.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())

    def test_qa_head_cannot_remove_one(self):
        dept = Department.objects.create(name='Temporary Office')
        self.client.force_login(make_user('remove_qa', 'qa_staff'))
        response = self.client.post(reverse('accounts:department_quick_delete', args=[dept.pk]))
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())


class DepartmentQuickAddTests(TestCase):
    """Adding a department from the account form, without leaving it."""

    def setUp(self):
        self.admin = make_user('quick_admin', 'admin')
        self.qa = make_user('quick_qa', 'qa_staff')
        self.url = reverse('accounts:department_quick_add')

    def test_administrator_can_add_one(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'name': 'Registrar Office'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['created'])
        self.assertEqual(body['name'], 'Registrar Office')
        self.assertTrue(Department.objects.filter(name='Registrar Office').exists())

    def test_new_department_is_offered_by_the_form(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {'name': 'Registrar Office'})
        self.assertIn('Registrar Office', dict(UserCreateForm().fields['department'].choices))

    def test_existing_name_returns_it_instead_of_failing(self):
        """The caller wanted that department available; it now is."""
        Department.objects.create(name='Registrar Office')
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'name': 'registrar office'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body['created'])
        self.assertEqual(body['name'], 'Registrar Office')
        self.assertEqual(Department.objects.filter(name__iexact='registrar office').count(), 1)

    def test_naming_an_inactive_department_brings_it_back(self):
        Department.objects.create(name='Library', is_active=False)
        self.client.force_login(self.admin)
        self.client.post(self.url, {'name': 'Library'})
        self.assertTrue(Department.objects.get(name='Library').is_active)

    def test_blank_name_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'name': '   '})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    def test_over_long_name_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'name': 'x' * 101})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Department.objects.filter(name__startswith='xxx').exists())

    def test_qa_head_cannot_add_one(self):
        self.client.force_login(self.qa)
        response = self.client.post(self.url, {'name': 'Sneaky Office'})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Department.objects.filter(name='Sneaky Office').exists())

    def test_anonymous_cannot_add_one(self):
        response = self.client.post(self.url, {'name': 'Sneaky Office'})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Department.objects.filter(name='Sneaky Office').exists())

    def test_get_is_refused(self):
        """Creating a row is a POST; a link or a prefetch must not do it."""
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

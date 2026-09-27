"""
Account fixes from the full system check.

* W-13c: a deactivated user signing in with the right password was told the
  password was wrong; the "deactivated" message was never reached.
* UM-08: the area checkboxes on the user form were in text order (IX between
  IV and V).
* S-RB-08: an area code could be added again in other capitals ("AREA I").
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from qa_structure.admin import AccreditationAreaForm
from qa_structure.models import AccreditationArea

ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']


class DeactivatedLoginTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('gone_user', password='pass12345')
        self.user.is_active = False
        self.user.save()

    def test_the_right_password_gets_the_deactivated_message(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'gone_user', 'password': 'pass12345'})
        self.assertContains(response, 'Your account has been deactivated.')

    def test_a_wrong_password_learns_nothing(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'gone_user', 'password': 'wrong-one'})
        self.assertNotContains(response, 'deactivated')
        self.assertContains(response, 'Invalid username or password.')


class AreaOrderTests(TestCase):

    def test_the_user_form_lists_areas_in_accreditation_order(self):
        for numeral in ROMAN:
            AccreditationArea.objects.get_or_create(area_code=f'Area {numeral}', defaults={'area_name': numeral})
        admin = User.objects.create_user('order_admin2', password='pass12345')
        admin.profile.role = 'admin'
        admin.profile.save()
        self.client.force_login(admin)
        html = self.client.get(reverse('accounts:user_create')).content.decode()
        positions = [html.find(f'Area {numeral}:') for numeral in ROMAN]
        self.assertTrue(all(p > 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions))


class AreaCodeUniquenessTests(TestCase):

    def test_the_same_code_in_other_capitals_is_refused(self):
        AccreditationArea.objects.get_or_create(area_code='Area I', defaults={'area_name': 'Vision'})
        form = AccreditationAreaForm(data={'area_code': 'AREA  i', 'area_name': 'Copy', 'description': '',
                                           'created_at_0': '2026-09-14', 'created_at_1': '10:00:00',
                                           'created_at': '2026-09-14 10:00:00'})
        self.assertFalse(form.is_valid())
        self.assertIn('Area "Area I" already exists.', form.errors['area_code'])

    def test_editing_an_area_keeps_its_own_code(self):
        area, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        form = AccreditationAreaForm(instance=area, data={'area_code': 'Area II', 'area_name': 'Faculty',
                                                          'description': '', 'created_at': '2026-09-14 10:00:00'})
        form.is_valid()
        self.assertNotIn('area_code', form.errors)

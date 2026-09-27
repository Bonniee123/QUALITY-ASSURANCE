"""
A Faculty account with no assigned area is told so instead of reaching a dead
end (S-AR-08): the bulk upload page offered only "- Select your area -", and the
refusal came after files had been chosen and submitted.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class NoAreaFacultyTests(TestCase):

    def setUp(self):
        user = User.objects.create_user('fac_none', password='pass12345')
        user.profile.role = 'faculty'
        user.profile.save()
        self.client.force_login(user)

    def test_the_upload_page_explains_instead_of_offering_an_empty_choice(self):
        response = self.client.get(reverse('documents:bulk_upload'), follow=True)
        self.assertRedirects(response, reverse('documents:repository'))
        self.assertContains(response, 'No accreditation area is assigned to your account yet.')

    def test_the_other_pages_still_open(self):
        for name in ('dashboard:home', 'documents:repository'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

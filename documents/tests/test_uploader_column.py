"""
The "Uploaded by" column and what its tooltip is for.

The column is capped at 130px and clips. Measured at a 1500px viewport, each
cell had 106px of room for 150px of content, so "Jester Limbaro Faculty" was cut
on every row. The note beside that cap in the stylesheet says the column is
"clipped like the title, with the full name on hover" -- but the markup put the
uploader's email address in the tooltip, so the one place the clipped name could
be read showed something else entirely, and an address the reader had not asked
for.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class UploaderTooltipTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.staff = User.objects.create_user('col_head', 'head@example.com', 'Str0ng-Passw0rd!')
        cls.staff.profile.role = 'qa_staff'
        cls.staff.profile.save()

        cls.named = User.objects.create_user(
            'col_fac', 'private.address@example.com', 'Str0ng-Passw0rd!',
            first_name='Jester', last_name='Limbaro')
        cls.named.profile.role = 'faculty'
        cls.named.profile.save()
        cls.named.profile.assigned_areas.add(cls.area)

        cls.nameless = User.objects.create_user('col_admin', 'admin@example.com', 'Str0ng-Passw0rd!')
        cls.nameless.profile.role = 'admin'
        cls.nameless.profile.save()

        for owner, title in ((cls.named, 'Faculty evidence'), (cls.nameless, 'Admin evidence')):
            Document.objects.create(
                title=title, file='uploaded_documents/%s.pdf' % owner.username, file_type='pdf',
                year=2026, document_type='Report', acc_area=cls.area, qa_area='Area II',
                uploaded_by=owner)

    def body(self):
        self.client.force_login(self.staff)
        return self.client.get(reverse('documents:repository')).content.decode()

    def test_the_tooltip_holds_the_name_the_cell_clips(self):
        self.assertIn('title="Jester Limbaro (Faculty)"', self.body())

    def test_the_email_address_is_no_longer_advertised(self):
        self.assertNotIn('private.address@example.com', self.body())

    def test_an_uploader_with_no_name_falls_back_to_their_username(self):
        """The cell shows the username in that case, so the tooltip matches it."""
        self.assertIn('title="col_admin"', self.body())

    def test_the_faculty_marker_is_only_on_faculty(self):
        body = self.body()
        self.assertEqual(body.count('(Faculty)"'), 1)
        self.assertNotIn('title="col_admin (Faculty)"', body)

"""
Saving a user says so, in words, on the page the administrator lands on.

A successful edit already redirected to the user's detail page with a Django
message attached. Two things were wrong with it in practice. It quoted the
account's *username* -- `User "faculty_area2" updated successfully.` -- which is
not how the person is named anywhere else in the interface, and it said nothing
about a password reset, which is the part of a save an administrator most needs
confirmed. It also closed itself after five seconds, along with every other
alert in the system including errors.

The confirmation now names the person, mentions the password when one was set,
and stays on screen for ten seconds; warnings and errors are no longer dismissed
for the reader at all.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from qa_structure.models import AccreditationArea


class EditConfirmationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.admin = User.objects.create_user('edit_admin', 'a@example.com', 'Str0ng-Passw0rd!')
        cls.admin.profile.role = 'admin'
        cls.admin.profile.save()
        cls.target = User.objects.create_user(
            'edit_target', 't@example.com', 'Str0ng-Passw0rd!',
            first_name='Faith', last_name='Cruz')
        cls.target.profile.role = 'faculty'
        cls.target.profile.status = 'active'
        cls.target.profile.save()

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        data = {
            'username': self.target.username,
            'first_name': self.target.first_name,
            'last_name': self.target.last_name,
            'email': self.target.email,
            'role': 'faculty',
            'department': 'QA Office',
            'status': 'active',
            'phone': '',
            'assigned_areas': [self.area.pk],
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def save(self, **overrides):
        return self.client.post(
            reverse('accounts:user_edit', args=[self.target.pk]),
            self.payload(**overrides), follow=True)

    def test_the_save_lands_on_the_user_with_a_confirmation(self):
        response = self.save()
        self.assertEqual(response.redirect_chain,
                         [(reverse('accounts:user_detail', args=[self.target.pk]), 302)])
        notes = [m.message for m in response.context['messages']]
        self.assertEqual(len(notes), 1)
        self.assertIn('Faith Cruz', notes[0])
        self.assertIn('saved', notes[0])

    def test_the_confirmation_is_actually_rendered(self):
        """A message in the context that no template prints is not a notification."""
        html = self.save().content.decode()
        self.assertIn('alert alert-success', html)
        self.assertIn('Faith Cruz', html[html.index('messages-container'):][:600])

    def test_it_names_the_person_not_the_username(self):
        notes = [m.message for m in self.save().context['messages']]
        self.assertNotIn('edit_target', notes[0])

    def test_a_blank_name_cannot_be_saved_at_all(self):
        """
        Which is why the username fallback in the message is defensive only:
        both name fields are required, so an account edited through this form
        always has a full name to be named by.
        """
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.target.pk]),
            self.payload(first_name='', last_name=''))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m.message for m in response.context['messages']], [])

    def test_a_password_reset_is_confirmed_too(self):
        notes = [m.message for m in self.save(
            new_password='An0ther-Str0ng-Pass!', new_password_confirm='An0ther-Str0ng-Pass!'
        ).context['messages']]
        self.assertIn('password was reset', notes[0])
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('An0ther-Str0ng-Pass!'))

    def test_a_save_without_a_password_does_not_claim_one_was_reset(self):
        notes = [m.message for m in self.save().context['messages']]
        self.assertNotIn('password', notes[0].lower())
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('Str0ng-Passw0rd!'),
                        'the existing password must be untouched')

    def test_a_rejected_edit_does_not_report_success(self):
        """Mismatched passwords: the form comes back, nothing claims it saved."""
        response = self.client.post(
            reverse('accounts:user_edit', args=[self.target.pk]),
            self.payload(new_password='An0ther-Str0ng-Pass!',
                         new_password_confirm='does-not-match'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m.message for m in response.context['messages']], [])

    def test_the_change_really_is_saved(self):
        """The notification has to be telling the truth."""
        self.save(email='faith.cruz@example.com')
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, 'faith.cruz@example.com')
        self.target.profile.refresh_from_db()
        self.assertEqual(self.target.profile.department, 'QA Office')


class AlertDwellTests(SimpleTestCase):
    """How long a message stays on screen."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = (settings.BASE_DIR / 'static' / 'js' / 'main.js').read_text(encoding='utf-8')

    def test_confirmations_stay_for_ten_seconds(self):
        self.assertIn('}, 10000);', self.js)
        self.assertNotIn('}, 5000);', self.js)

    def test_errors_and_warnings_are_not_dismissed_for_the_reader(self):
        block = self.js[self.js.index('Auto-dismiss confirmations'):]
        block = block[:block.index('// Confirm before delete')]
        for cls in ('alert-danger', 'alert-error', 'alert-warning'):
            self.assertIn(cls, block)
        self.assertIn('return;', block)

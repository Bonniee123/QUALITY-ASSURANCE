"""
"Show password" is a labelled checkbox, not an eye.

Both password surfaces in the system -- the sign-in page and the password
fields on the Create/Edit User form -- had an eye button sitting inside the
field. An eye states its meaning through an icon and a hover tooltip, its two
states look alike at a glance, and on the user form there were two of them for
a pair of fields that are always compared with each other.

Each is now a checkbox that says "Show password" in words: checked reveals,
unchecked hides again. Nothing else changed. The fields are still ordinary
password inputs, the form still posts the same names to the same view, and the
script only ever sets `type` -- it never reads or writes what was typed.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

TEMPLATES = settings.BASE_DIR / 'templates' / 'accounts'


def source(name):
    return (TEMPLATES / name).read_text(encoding='utf-8')


class LoginPageTests(TestCase):

    def page(self):
        return self.client.get(reverse('accounts:login')).content.decode()

    def test_the_eye_button_is_gone(self):
        html = self.page()
        for gone in ('id="togglePw"', 'togglePwIcon', 'bi-eye-slash'):
            self.assertNotIn(gone, html)

    def test_there_is_a_labelled_checkbox(self):
        html = self.page()
        self.assertIn('id="showPw"', html)
        self.assertIn('Show password', html)
        self.assertIn('type="checkbox"', html[html.index('id="showPw"') - 80:])

    def test_the_field_is_still_a_password_field(self):
        html = self.page()
        field = html[html.index('id="login-password"') - 200:html.index('id="login-password"') + 200]
        self.assertIn('type="password"', field)

    def test_signing_in_still_works(self):
        """The checkbox is display only; authentication is untouched."""
        user = User.objects.create_user('pw_user', 'p@example.com', 'Str0ng-Passw0rd!')
        response = self.client.post(reverse('accounts:login'),
                                    {'username': user.username, 'password': 'Str0ng-Passw0rd!'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_a_wrong_password_is_still_refused(self):
        User.objects.create_user('pw_user2', 'p2@example.com', 'Str0ng-Passw0rd!')
        response = self.client.post(reverse('accounts:login'),
                                    {'username': 'pw_user2', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


class UserFormTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('pw_admin', 'a@example.com', 'Str0ng-Passw0rd!')
        cls.admin.profile.role = 'admin'
        cls.admin.profile.save()

    def page(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('accounts:user_create')).content.decode()

    def test_both_eye_buttons_are_gone(self):
        html = self.page()
        self.assertNotIn('uf-eye', html)
        self.assertNotIn('data-toggle="#id_password"', html)

    def test_one_checkbox_covers_the_pair(self):
        html = self.page()
        self.assertEqual(html.count('id="ufShowPw"'), 1)
        self.assertIn('Show password', html)

    def test_both_fields_are_still_password_fields(self):
        html = self.page()
        for field_id in ('id_password', 'id_password_confirm'):
            position = html.index(field_id)
            self.assertIn('type="password"', html[position - 200:position + 200],
                          '%s should still be a password input' % field_id)


class ScriptTests(SimpleTestCase):
    """What the two scripts are allowed to do."""

    def test_the_login_script_only_switches_the_field_type(self):
        js = source('login.html')
        block = js[js.index("var showPw = document.getElementById('showPw');"):]
        block = block[:block.index('var form = document.getElementById')]
        self.assertIn("pwInput.type = showPw.checked ? 'text' : 'password';", block)
        self.assertNotIn('.value', block)

    def test_the_user_form_script_only_switches_the_field_type(self):
        js = source('user_form.html')
        block = js[js.index('function applyPwVisibility()'):]
        block = block[:block.index('}\n')]
        self.assertIn("input.type = showPw && showPw.checked ? 'text' : 'password';", block)
        self.assertNotIn('.value', block)

    def test_generating_a_password_ticks_the_box_it_agrees_with(self):
        """The generated password is revealed, so the checkbox must say so."""
        js = source('user_form.html')
        block = js[js.index("const genBtn = document.getElementById('genPassBtn');"):]
        block = block[:block.index('// Show the accreditation-area picker')]
        self.assertIn('showPw.checked = true;', block)
        self.assertIn('applyPwVisibility();', block)

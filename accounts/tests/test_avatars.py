"""
Resolving an account's picture.

The helpers behind every avatar in the system. They have to survive the two
shapes that reach them from real pages -- an account with no profile row, and no
account at all, where an uploader has since been deleted -- because a page that
raises is worse than a page showing initials.
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.avatars import avatar_url, identity, initials, profile_of
from accounts.models import UserProfile

# Smallest thing an ImageField will accept.
GIF = (b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00'
       b'\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;')


def photo(name='p.gif'):
    return SimpleUploadedFile(name, GIF, content_type='image/gif')


class AvatarResolutionTests(TestCase):

    def setUp(self):
        self.with_photo = User.objects.create_user(
            'haspic', 'a@e.com', 'testpass123', first_name='Ada', last_name='Reyes')
        self.with_photo.profile.avatar = photo('ada.gif')
        self.with_photo.profile.save()

        self.no_photo = User.objects.create_user(
            'nopic', 'b@e.com', 'testpass123', first_name='Bea', last_name='Cruz')

    def test_photo_url_is_returned_for_an_account_that_has_one(self):
        self.assertIn('ada', avatar_url(self.with_photo))

    def test_no_photo_is_empty_not_a_placeholder(self):
        """Callers fall back to initials, so '' has to be the answer."""
        self.assertEqual(avatar_url(self.no_photo), '')

    def test_account_with_no_profile_row_does_not_raise(self):
        stray = User.objects.create_user('stray', 'c@e.com', 'testpass123',
                                         first_name='Cy', last_name='Diaz')
        UserProfile.objects.filter(user=stray).delete()
        stray = User.objects.get(pk=stray.pk)
        self.assertIsNone(profile_of(stray))
        self.assertEqual(avatar_url(stray), '')
        self.assertEqual(initials(stray), 'CD')

    def test_missing_account_does_not_raise(self):
        """A deleted uploader still reaches these call sites."""
        self.assertEqual(avatar_url(None), '')
        self.assertEqual(initials(None), '?')

    def test_initials_come_from_the_name(self):
        self.assertEqual(initials(self.no_photo), 'BC')

    def test_initials_fall_back_to_the_username(self):
        anon = User.objects.create_user('zephyr', 'd@e.com', 'testpass123')
        self.assertEqual(initials(anon), 'ZE')

    def test_identity_bundles_name_photo_and_initials(self):
        row = identity(self.with_photo)
        self.assertEqual(row['name'], 'Ada Reyes')
        self.assertEqual(row['initials'], 'AR')
        self.assertIn('ada', row['avatar'])

    def test_identity_of_a_deleted_account_is_labelled_not_blank(self):
        self.assertEqual(identity(None)['name'], 'Deleted user')


class AvatarIsPerAccountNotPerRoleTests(TestCase):
    """
    The picture belongs to the account.

    Two accounts sharing a role must not share a picture, and changing a role
    must not change the picture -- that is the whole point of storing it on the
    profile rather than deriving it.
    """

    def test_two_accounts_with_the_same_role_keep_different_pictures(self):
        urls = set()
        for name in ('qa_one', 'qa_two'):
            user = User.objects.create_user(name, f'{name}@e.com', 'testpass123')
            user.profile.role = 'qa_staff'
            user.profile.avatar = photo(f'{name}.gif')
            user.profile.save()
            urls.add(avatar_url(user))
        self.assertEqual(len(urls), 2)

    def test_changing_role_leaves_the_picture_alone(self):
        user = User.objects.create_user('mover', 'm@e.com', 'testpass123')
        user.profile.avatar = photo('mover.gif')
        user.profile.role = 'faculty'
        user.profile.save()
        before = avatar_url(user)

        user.profile.role = 'admin'
        user.profile.save()
        self.assertEqual(avatar_url(user), before)


class AvatarUploadValidationTests(TestCase):
    """
    A profile picture has to be a picture, in a format we serve.

    Profile photos are the one thing under /media/ readable without signing in,
    so what may be stored there is worth being strict about: the browser's
    content type is only the uploader's word, and the file's real format is not.
    """

    def validate(self, upload):
        from django.forms import ImageField

        from accounts.forms import _validate_avatar
        # The same path the form takes: the field decodes it, then our rules run.
        return _validate_avatar(ImageField(required=False).clean(upload))

    def image(self, fmt, size=(8, 8), name=None, content_type=None):
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', size, (20, 60, 120)).save(buf, fmt)
        return SimpleUploadedFile(name or f'p.{fmt.lower()}', buf.getvalue(),
                                  content_type=content_type or f'image/{fmt.lower()}')

    def test_a_normal_photo_is_accepted(self):
        for fmt in ('PNG', 'JPEG', 'GIF', 'WEBP'):
            with self.subTest(fmt=fmt):
                self.assertIsNotNone(self.validate(self.image(fmt)))

    def test_a_document_renamed_as_a_picture_is_refused(self):
        from django.core.exceptions import ValidationError
        upload = SimpleUploadedFile('photo.png', b'%PDF-1.4 not a picture', content_type='image/png')
        with self.assertRaises(ValidationError):
            self.validate(upload)

    def test_a_format_we_do_not_serve_is_refused(self):
        from django.core.exceptions import ValidationError
        # A real BMP calling itself a PNG: openable, but not one of ours.
        with self.assertRaises(ValidationError):
            self.validate(self.image('BMP', name='sneaky.png', content_type='image/png'))

    def test_a_picture_with_absurd_dimensions_is_refused(self):
        from unittest import mock

        from django.core.exceptions import ValidationError
        with mock.patch('accounts.forms.MAX_AVATAR_PIXELS', 16):
            with self.assertRaises(ValidationError):
                self.validate(self.image('PNG', size=(8, 8)))

"""
Forms for user authentication and management.
"""
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from .models import Department, UserProfile

try:
    from qa_structure.models import AccreditationArea
except Exception:  # pragma: no cover
    AccreditationArea = None

BLANK_DEPARTMENT = ('', 'Select department / office')


def department_choices():
    """
    The department dropdown, built from the Department table.

    This used to be a hard-coded constant, so adding an office meant editing
    code. Read at render time rather than at import so a department added
    during a session appears without restarting the server.

    Falls back to the blank entry alone if the table cannot be read -- during
    the migration that creates it, for instance. An empty dropdown is a smaller
    problem than a form that raises.
    """
    choices = [BLANK_DEPARTMENT]
    try:
        choices += [
            (name, name)
            for name in Department.objects.filter(is_active=True)
                                          .order_by('name')
                                          .values_list('name', flat=True)
        ]
    except Exception:  # pragma: no cover - table missing or unreadable
        pass
    return choices


def _accreditation_area_queryset():
    """
    All accreditation areas in accreditation order -- Area I, II ... IX, X -- or
    an empty queryset if the model is unavailable. Sorted as text, Area IX came
    between IV and V.
    """
    if AccreditationArea is None:
        return None
    try:
        from django.db.models import Case, IntegerField, Value, When
        from qa_structure.utils_ordering import area_roman_sort_key

        rows = sorted(AccreditationArea.objects.values_list('pk', 'area_code'),
                      key=lambda row: area_roman_sort_key(row[1]))
        if not rows:
            return AccreditationArea.objects.all()
        position = Case(*[When(pk=pk, then=Value(i)) for i, (pk, _code) in enumerate(rows)],
                        output_field=IntegerField())
        return AccreditationArea.objects.annotate(accreditation_order=position).order_by('accreditation_order')
    except Exception:  # pragma: no cover
        return AccreditationArea.objects.none()


def _assigned_areas_field():
    """Checkbox list for the Faculty area assignment (only relevant when role=faculty)."""
    qs = _accreditation_area_queryset()
    return forms.ModelMultipleChoiceField(
        queryset=qs if qs is not None else AccreditationArea.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'qa-area-checks',
            'data-faculty-areas': '1',
        }),
        help_text='Tick every area this faculty member is responsible for. Used only for Faculty accounts.',
    )

# Names: letters plus spaces, hyphens, apostrophes and periods. No digits/symbols.
NAME_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z][A-Za-z .'\-]*$",
    message="Only letters, spaces, hyphens, apostrophes and periods are allowed.",
)
# Username: letters/digits and a small set of safe symbols, must start with a letter.
USERNAME_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z][A-Za-z0-9._-]{2,}$",
    message="Start with a letter; use only letters, numbers, dot, underscore or hyphen (min 3 characters).",
)
# Phone: digits and common separators only.
PHONE_VALIDATOR = RegexValidator(
    regex=r"^[0-9+\-() ]{7,20}$",
    message="Enter a valid phone number (digits and + - ( ) only).",
)

ALLOWED_AVATAR_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
# What the picture must be once opened, whatever the browser called it.
ALLOWED_AVATAR_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}
MAX_AVATAR_BYTES = 3 * 1024 * 1024  # 3 MB
# Profile pictures are shown at 38 pixels; a file approaching this is asking the
# server to allocate memory, not offering a photograph.
MAX_AVATAR_PIXELS = 30_000_000


def _validate_avatar(image):
    """
    Shared avatar size and type validation.

    The form field already refuses anything Pillow cannot open, which rules out a
    document renamed ".png". Added here: the file's real format -- the browser's
    content type is only the uploader's word, and a TIFF or an ICO would
    otherwise be stored and served under a .png name -- and a pixel budget, since
    a small file can declare enormous dimensions.
    """
    if not image:
        return image
    if image.size > MAX_AVATAR_BYTES:
        raise forms.ValidationError("Image is too large (maximum 3 MB).")
    content_type = getattr(image, 'content_type', None)
    if content_type and content_type.split(';')[0].strip().lower() not in ALLOWED_AVATAR_TYPES:
        raise forms.ValidationError("Unsupported image type. Use JPG, PNG, WEBP or GIF.")
    # Django's ImageField leaves the opened picture on the file as .image.
    opened = getattr(image, 'image', None)
    fmt = (getattr(opened, 'format', '') or '').upper()
    if fmt and fmt not in ALLOWED_AVATAR_FORMATS:
        raise forms.ValidationError("Unsupported image type. Use JPG, PNG, WEBP or GIF.")
    width, height = getattr(opened, 'size', None) or (0, 0)
    if width * height > MAX_AVATAR_PIXELS:
        raise forms.ValidationError("Image dimensions are too large. Use a picture under 30 megapixels.")
    return image


class LoginForm(forms.Form):
    """Login form with styled widgets."""
    username = forms.CharField(
        max_length=254,
        label='Username or email',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your username or email',
            'id': 'login-username',
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'id': 'login-password',
            'autocomplete': 'current-password',
        })
    )


class UserCreateForm(forms.ModelForm):
    """Form for creating new users with profile fields."""
    first_name = forms.CharField(
        max_length=150,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'First name',
            'pattern': r"[A-Za-z][A-Za-z .'\-]*", 'data-strict': 'name',
            'title': 'Letters only — no numbers or symbols.',
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Last name',
            'pattern': r"[A-Za-z][A-Za-z .'\-]*", 'data-strict': 'name',
            'title': 'Letters only — no numbers or symbols.',
        }),
    )
    phone = forms.CharField(
        required=False,
        max_length=20,
        validators=[PHONE_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'e.g. +63 912 345 6789',
            'data-strict': 'phone', 'inputmode': 'tel',
            'title': 'Digits and + - ( ) only.',
        }),
    )
    avatar = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control', 'accept': 'image/png,image/jpeg,image/webp,image/gif',
            'id': 'id_avatar',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Enter password',
            'id': 'id_password', 'autocomplete': 'new-password',
        })
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Confirm password',
            'id': 'id_password_confirm', 'autocomplete': 'new-password',
        })
    )
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'data-role-select': '1'})
    )
    department = forms.ChoiceField(
        choices=[BLANK_DEPARTMENT],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Username',
                'pattern': r"[A-Za-z][A-Za-z0-9._-]{2,}", 'data-strict': 'username',
                'title': 'Start with a letter; letters, numbers, . _ - only.',
            }),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_areas'] = _assigned_areas_field()
        # Read the departments now rather than at import, so one added a moment
        # ago is offered without restarting the server.
        self.fields['department'].choices = department_choices()

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        USERNAME_VALIDATOR(username)
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_avatar(self):
        return _validate_avatar(self.cleaned_data.get('avatar'))

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        pw2 = cleaned_data.get('password_confirm')
        if pw and pw2 and pw != pw2:
            self.add_error('password_confirm', "Passwords do not match.")
        elif pw:
            try:
                validate_password(pw)
            except ValidationError as exc:
                self.add_error('password', exc)
        if cleaned_data.get('role') == 'faculty' and not cleaned_data.get('assigned_areas'):
            self.add_error('assigned_areas', 'Assign at least one accreditation area for a Faculty account.')
        return cleaned_data


class UserEditForm(forms.ModelForm):
    """Form for editing existing users."""
    first_name = forms.CharField(
        max_length=150,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'pattern': r"[A-Za-z][A-Za-z .'\-]*",
            'data-strict': 'name', 'title': 'Letters only — no numbers or symbols.',
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        validators=[NAME_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'pattern': r"[A-Za-z][A-Za-z .'\-]*",
            'data-strict': 'name', 'title': 'Letters only — no numbers or symbols.',
        }),
    )
    phone = forms.CharField(
        required=False,
        max_length=20,
        validators=[PHONE_VALIDATOR],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'e.g. +63 912 345 6789',
            'data-strict': 'phone', 'inputmode': 'tel',
            'title': 'Digits and + - ( ) only.',
        }),
    )
    avatar = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control', 'accept': 'image/png,image/jpeg,image/webp,image/gif',
            'id': 'id_avatar',
        }),
    )
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Leave blank to keep current password',
            'id': 'id_password', 'autocomplete': 'new-password',
        }),
        help_text="Existing passwords cannot be shown. Enter a value here only to reset it.",
    )
    new_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Confirm new password',
            'id': 'id_password_confirm', 'autocomplete': 'new-password',
        }),
    )
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'data-role-select': '1'})
    )
    department = forms.ChoiceField(
        choices=[BLANK_DEPARTMENT],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        choices=UserProfile.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control', 'pattern': r"[A-Za-z][A-Za-z0-9._-]{2,}",
                'data-strict': 'username', 'title': 'Start with a letter; letters, numbers, . _ - only.',
            }),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_areas'] = _assigned_areas_field()
        self.fields['department'].choices = department_choices()
        if self.instance and self.instance.pk:
            # A department that was renamed, deactivated or deleted is still
            # shown for the account that records it, so editing anything else
            # about that account does not silently clear the field.
            current_dept = (getattr(self.instance.profile, 'department', '') or '').strip()
            if current_dept and current_dept not in dict(self.fields['department'].choices):
                self.fields['department'].choices = list(self.fields['department'].choices) + [
                    (current_dept, current_dept),
                ]
            profile = getattr(self.instance, 'profile', None)
            if profile is not None and not self.is_bound:
                self.fields['assigned_areas'].initial = list(
                    profile.assigned_areas.values_list('pk', flat=True)
                )

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        USERNAME_VALIDATOR(username)
        qs = User.objects.filter(username__iexact=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_avatar(self):
        return _validate_avatar(self.cleaned_data.get('avatar'))

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('new_password')
        pw2 = cleaned_data.get('new_password_confirm')
        if pw or pw2:
            if pw != pw2:
                self.add_error('new_password_confirm', "Passwords do not match.")
            else:
                try:
                    validate_password(pw, self.instance)
                except ValidationError as exc:
                    self.add_error('new_password', exc)
        if cleaned_data.get('role') == 'faculty' and not cleaned_data.get('assigned_areas'):
            self.add_error('assigned_areas', 'Assign at least one accreditation area for a Faculty account.')
        return cleaned_data


class DepartmentForm(forms.ModelForm):
    """Create or rename a department shown in the account dropdown."""

    class Meta:
        model = Department
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Registrar\'s Office',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional note about this department or office.',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'is_active': 'Uncheck to take it out of the dropdown without '
                         'affecting accounts that already record it.',
        }

    def clean_name(self):
        """
        Names must be unique whatever their casing.

        The model's unique constraint is case-sensitive on some databases, so
        "QA office" and "QA Office" could both be stored and then appear as two
        separate entries in the same dropdown.
        """
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError('Enter a department or office name.')
        clash = Department.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError('A department with that name already exists.')
        return name

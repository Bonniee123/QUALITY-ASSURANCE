"""
User profile model extending Django's built-in User.
Adds role, department, and status fields for role-based access control.
"""
from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """Extended user profile with role-based access control."""

    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('qa_staff', 'QA Head'),
        ('faculty', 'Faculty'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='qa_staff')
    department = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    phone = models.CharField(max_length=20, blank=True, default='')
    avatar = models.ImageField(upload_to='profile_pics/%Y/%m/', blank=True, null=True)
    # Accreditation areas a Faculty member is responsible for. Empty for Admin/QA Head
    # (they see every area). Faculty are scoped to upload and view only these areas.
    assigned_areas = models.ManyToManyField(
        'qa_structure.AccreditationArea',
        blank=True,
        related_name='faculty_profiles',
        help_text='Areas this faculty member may upload to and view. Ignored for Admin / QA Head.',
    )

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_qa_staff(self):
        return self.role == 'qa_staff'

    @property
    def is_faculty(self):
        return self.role == 'faculty'

    @property
    def assigned_area_codes(self):
        """List of area_code strings assigned to this profile."""
        return list(self.assigned_areas.values_list('area_code', flat=True))

    @property
    def avatar_url(self):
        """Return the avatar URL if an image is set, else an empty string."""
        if self.avatar:
            try:
                return self.avatar.url
            except ValueError:
                return ''
        return ''

    @property
    def initials(self):
        """Two-letter initials from full name, falling back to the username."""
        name = (self.user.get_full_name() or self.user.username).strip()
        parts = [p for p in name.split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        if parts:
            return parts[0][:2].upper()
        return 'U'


class Department(models.Model):
    """
    A department or office an account can belong to.

    This list used to be a constant in accounts/forms.py holding a single entry,
    so adding an office meant editing code. These rows now fill the same
    dropdown and an Administrator maintains them from the system.

    UserProfile.department deliberately stays a text field rather than becoming
    a foreign key to this model. Keeping the text means removing a department
    never rewrites anyone's profile and never forces a decision about what a
    user with a deleted department should look like: the name already stored on
    a profile keeps displaying whether or not a row still exists for it.
    Prefer deactivating a department to deleting it, which takes it out of the
    dropdown while leaving the people recorded against it untouched.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(
        default=True,
        help_text='Only active departments are offered when choosing one for an account.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        """How many accounts record this department, matched on the stored name."""
        return UserProfile.objects.filter(department=self.name).count()


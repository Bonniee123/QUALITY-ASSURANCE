"""
Signals to auto-create UserProfile when a User is created.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, raw=False, **kwargs):
    """Create a UserProfile whenever a new User is created."""
    if raw:
        # Fixture load (loaddata, or migrating between database backends). The
        # fixture carries its own UserProfile rows, so creating one here collides
        # with them on the OneToOne user_id constraint. Related tables may also be
        # unpopulated mid-load, so a raw save must never write to the database.
        return
    if created:
        # Superusers get admin role by default; office users default to QA Head.
        role = 'admin' if instance.is_superuser else 'qa_staff'
        UserProfile.objects.create(user=instance, role=role)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, raw=False, **kwargs):
    """Save the UserProfile whenever the User is saved."""
    if raw:
        return
    if hasattr(instance, 'profile'):
        instance.profile.save()

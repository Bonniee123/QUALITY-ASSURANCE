"""
Management command to create the default admin account.
Usage: python manage.py create_default_admin
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create default admin user (admin/admin123)'

    def handle(self, *args, **options):
        if User.objects.filter(username='admin').exists():
            self.stdout.write(self.style.WARNING('Admin user already exists.'))
            return

        user = User.objects.create_superuser(
            username='admin',
            email='admin@qaarchive.local',
            password='admin123',
            first_name='System',
            last_name='Administrator',
        )
        # Profile is auto-created via signal with admin role
        user.profile.role = 'admin'
        user.profile.department = 'QA Office'
        user.profile.save()

        self.stdout.write(self.style.SUCCESS(
            'Default admin created:\n'
            '  Username: admin\n'
            '  Password: admin123\n'
            '  Role: Admin'
        ))

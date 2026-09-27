"""
Management command to create the default QA Head account.
Usage: python manage.py create_default_qa_head
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create default QA Head user (qahead/qahead123)'

    def handle(self, *args, **options):
        if User.objects.filter(username='qahead').exists():
            self.stdout.write(self.style.WARNING('QA Head user already exists.'))
            return

        user = User.objects.create_user(
            username='qahead',
            email='qahead@qaarchive.local',
            password='qahead123',
            first_name='QA',
            last_name='Head',
        )
        user.profile.role = 'qa_staff'
        user.profile.department = 'QA Office'
        user.profile.status = 'active'
        user.profile.save()

        self.stdout.write(self.style.SUCCESS(
            'Default QA Head created:\n'
            '  Username: qahead\n'
            '  Password: qahead123\n'
            '  Role: QA Head (qa_staff)'
        ))

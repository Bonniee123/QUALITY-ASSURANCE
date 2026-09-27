"""
Management command to create demo Faculty accounts for the capstone demo / defense.

Idempotent: re-running it will not create duplicates, and it re-applies each
account's assigned area(s). Faculty are scoped to upload and view only their areas.

Usage: python manage.py create_demo_faculty
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from qa_structure.models import AccreditationArea

# (username, password, first, last, [area_codes])
DEMO_FACULTY = [
    ('faculty_area2', 'faculty123', 'Faith', 'Cruz', ['Area II']),
    ('faculty_area3', 'faculty123', 'Marco', 'Reyes', ['Area III']),
    ('faculty_multi', 'faculty123', 'Liza', 'Santos', ['Area IV', 'Area V']),
]


class Command(BaseCommand):
    help = 'Create demo Faculty accounts, each scoped to one or more accreditation areas.'

    def handle(self, *args, **options):
        created, updated, missing = 0, 0, set()

        for username, password, first, last, area_codes in DEMO_FACULTY:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_user(
                    username=username,
                    email=f'{username}@qaarchive.local',
                    password=password,
                    first_name=first,
                    last_name=last,
                )
                created += 1
            else:
                updated += 1

            user.profile.role = 'faculty'
            user.profile.status = 'active'
            user.profile.save()

            areas = []
            for code in area_codes:
                area = AccreditationArea.objects.filter(area_code=code).first()
                if area is None:
                    missing.add(code)
                    continue
                areas.append(area)
            user.profile.assigned_areas.set(areas)

            self.stdout.write(
                f'  {username} / {password}  ->  {", ".join(area_codes) or "(no areas found)"}'
            )

        self.stdout.write(self.style.SUCCESS(
            f'\nDemo faculty ready. Created: {created}, updated: {updated}.'
        ))
        if missing:
            self.stdout.write(self.style.WARNING(
                'These area codes were not found (seed the QA structure first): '
                + ', '.join(sorted(missing))
            ))

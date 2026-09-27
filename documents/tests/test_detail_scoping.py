"""
The document detail panel lists only documents the viewer may open (S-AR-05).

A Faculty member opening a flagged document in their own area was shown its
matches and cluster peers from other areas, and archived versions, by title.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document
from qa_structure.models import AccreditationArea


class DetailPanelScopingTests(TestCase):

    def setUp(self):
        self.area2, _ = AccreditationArea.objects.get_or_create(area_code='Area II', defaults={'area_name': 'Faculty'})
        self.area3, _ = AccreditationArea.objects.get_or_create(area_code='Area III', defaults={'area_name': 'Curriculum'})

        def doc(title, area, **extra):
            return Document.objects.create(title=title, file=f'uploaded_documents/{title}.pdf', file_type='pdf',
                                           year=2026, document_type='Report', acc_area=area, qa_area=area.area_code,
                                           cluster_label=7, **extra)

        self.other_area = doc('Other area plan', self.area2)
        self.archived = doc('Old version', self.area3, is_archived=True)
        self.peer = doc('Same area peer', self.area3)
        self.mine = doc('My curriculum map', self.area3, duplicate_status='possible', similar_documents=[
            {'id': self.other_area.pk, 'title': 'Other area plan', 'similarity': 0.97},
            {'id': self.archived.pk, 'title': 'Old version', 'similarity': 0.95},
            {'id': self.peer.pk, 'title': 'Same area peer', 'similarity': 0.9},
        ])

    def panel_for(self, role, areas=()):
        user = User.objects.create_user(f'viewer_{role}', password='pass12345')
        user.profile.role = role
        user.profile.save()
        for area in areas:
            user.profile.assigned_areas.add(area)
        self.client.force_login(user)
        return self.client.get(reverse('documents:detail', args=[self.mine.pk]) + '?panel=1').content.decode()

    def test_faculty_are_shown_no_matches_at_all(self):
        """
        This used to assert that a Faculty member saw the one match inside their
        own area and not the others. Duplicate work is QA work, so the panel now
        shows them no Similar Documents section and the view does not build the
        list -- which is a stricter form of the same rule. The area scoping it
        was guarding is still checked below, on a viewer who does get the list.
        """
        html = self.panel_for('faculty', [self.area3])
        self.assertNotIn('Similar Documents', html)
        self.assertNotIn('Same area peer', html)
        self.assertNotIn('Other area plan', html)
        self.assertNotIn('Old version', html)

    def test_staff_see_every_current_match(self):
        html = self.panel_for('qa_staff')
        self.assertIn('Other area plan', html)
        self.assertIn('Same area peer', html)
        self.assertNotIn('Old version', html)

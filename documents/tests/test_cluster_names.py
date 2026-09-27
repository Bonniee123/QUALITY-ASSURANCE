"""
Cluster numbers carry their descriptive name wherever only the number is shown.

The AI Processing and Clusters pages name each cluster ("Area III · Report ·
library, holdings"); the Repository column and filter, the Reports and the
Dashboard showed only "C3" / "Cluster 3" (S-CL-06). The number stays as it was,
and its name is now on hover.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import ClusterResult, Document

NAME = 'Area III · Report · library, holdings'


class ClusterNameOnHoverTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user('names_admin', password='pass12345')
        self.admin.profile.role = 'admin'
        self.admin.profile.save()
        doc = Document.objects.create(title='Library report', file='uploaded_documents/lib.pdf', file_type='pdf',
                                      year=2026, document_type='Report', cluster_label=3, is_processed=True)
        ClusterResult.objects.create(document=doc, cluster_number=3, cluster_label=NAME, top_keywords=['library'])
        self.client.force_login(self.admin)

    def test_repository_column_and_filter(self):
        html = self.client.get(reverse('documents:repository')).content.decode()
        self.assertIn(f'title="{NAME}">C3</span>', html)
        self.assertIn(f'<option value="3" title="{NAME}"', html)

    def test_reports(self):
        inventory = self.client.get(reverse('reports:page') + '?type=inventory').content.decode()
        self.assertIn(f'title="{NAME}">C3</span>', inventory)
        clusters = self.client.get(reverse('reports:page') + '?type=cluster').content.decode()
        self.assertIn(f'title="{NAME}">Cluster 3</span>', clusters)

    def test_dashboard(self):
        self.assertIn(f'title="{NAME}">C3</span>', self.client.get(reverse('dashboard:home')).content.decode())

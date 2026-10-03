"""
Document versions (W-14, S-DATA-01, S-DATA-02).

Before: "B supersedes A" followed by "A supersedes B" was accepted and made a
cycle (the check walked the wrong way); Unarchive left the newer document still
pointing at the restored one; and deleting the newer version left the older one
archived with nothing pointing at it -- unreachable from any page.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import Document


class VersionTests(TestCase):

    def setUp(self):
        head = User.objects.create_user('ver_head', password='pass12345')
        head.profile.role = 'qa_staff'
        head.profile.save()
        self.client.force_login(head)

        def doc(title):
            return Document.objects.create(title=title, file=f'uploaded_documents/{title}.pdf', file_type='pdf',
                                           year=2026, document_type='Manual')

        self.a, self.b, self.c = doc('Manual v1'), doc('Manual v2'), doc('Manual v3')

    def supersede(self, newer, older):
        return self.client.post(reverse('documents:mark_as_version', args=[newer.pk]),
                                {'previous_id': older.pk}, follow=True)

    def refresh(self):
        for d in (self.a, self.b, self.c):
            d.refresh_from_db()

    def test_supersede_archives_the_older_one(self):
        self.supersede(self.b, self.a)
        self.refresh()
        self.assertEqual((self.a.is_archived, self.b.previous_version_id), (True, self.a.pk))

    def test_a_direct_cycle_is_refused(self):
        self.supersede(self.b, self.a)
        response = self.supersede(self.a, self.b)
        self.assertContains(response, 'That would create a version cycle.')
        self.refresh()
        self.assertIsNone(self.a.previous_version_id)
        self.assertFalse(self.b.is_archived)

    def test_a_longer_cycle_is_refused(self):
        self.supersede(self.b, self.a)
        self.supersede(self.c, self.b)
        self.assertContains(self.supersede(self.a, self.c), 'That would create a version cycle.')

    def test_unarchive_takes_the_document_out_of_the_chain(self):
        self.supersede(self.b, self.a)
        self.client.post(reverse('documents:unarchive', args=[self.a.pk]))
        self.refresh()
        self.assertFalse(self.a.is_archived)
        self.assertIsNone(self.b.previous_version_id)
        # ...so linking them the other way round is now a plain supersede, not a cycle.
        self.supersede(self.a, self.b)
        self.refresh()
        self.assertEqual((self.a.previous_version_id, self.b.is_archived), (self.b.pk, True))

    def test_deleting_the_newer_version_restores_the_older_one(self):
        self.supersede(self.b, self.a)
        self.client.post(reverse('documents:delete', args=[self.b.pk]))
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_archived, 'the older version is reachable again')

    def test_bulk_deleting_the_newer_version_restores_the_older_one(self):
        self.supersede(self.b, self.a)
        self.client.post(reverse('documents:bulk_delete'), {'document_ids': [self.b.pk]})
        self.a.refresh_from_db()
        self.assertFalse(self.a.is_archived)

    def test_deleting_both_versions_restores_nothing(self):
        """
        Deleting a whole version pair leaves nothing behind in the repository.

        Both rows survive, because a bulk delete is reversible, but neither is
        reachable: there is no half-restored chain where the older version
        reappears because the newer one went away.
        """
        self.supersede(self.b, self.a)
        self.client.post(reverse('documents:bulk_delete'), {'document_ids': [self.a.pk, self.b.pk]})
        self.assertFalse(
            Document.objects.live().filter(pk__in=[self.a.pk, self.b.pk]).exists())
        self.assertEqual(
            Document.objects.deleted().filter(pk__in=[self.a.pk, self.b.pk]).count(), 2)

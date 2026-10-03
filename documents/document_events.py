"""
What happens around an upload: its history entry and the notification.

The history entry is written from a post_save signal, so every way a document
can be created -- bulk upload, the Faculty single-file page, the structured
upload, an import script -- records who uploaded what and when, without each
path having to remember to.

The notification is sent by the upload views once per upload action, so a
batch of twenty files is one "uploaded 20 documents" and not twenty.
"""
import os

from django.db.models.signals import post_save
from django.dispatch import receiver

from .audit import person_name, record_document_event
from .models import Document


@receiver(post_save, sender=Document, dispatch_uid='documents.record_upload')
def record_upload(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    if not instance.original_filename and instance.file:
        name = os.path.basename(instance.file.name)[:255]
        Document.objects.filter(pk=instance.pk).update(original_filename=name)
        instance.original_filename = name
    record_document_event(
        instance, 'upload_document', instance.uploaded_by,
        description=f'Uploaded document: {instance.title} ({instance.original_filename or "no file"})',
    )


def announce_uploads(uploader, documents):
    """
    "New Document — Faculty A uploaded Report.pdf" to Administrators and QA Heads.

    The key is built from the document ids, so the same upload announced twice
    (a retried request, a second caller) notifies once.
    """
    documents = [d for d in documents if d is not None]
    if not documents:
        return 0
    from django.urls import reverse
    from notifications.services import notify_qa_staff

    who = person_name(uploader) or 'Someone'
    if len(documents) == 1:
        doc = documents[0]
        message = f'New Document — {who} uploaded "{doc.title}"'
        link = f"{reverse('documents:repository')}?q={doc.title[:80]}"
    else:
        message = f'New Documents — {who} uploaded {len(documents)} documents'
        link = reverse('documents:repository')
    key = 'uploaded:' + ','.join(str(d.pk) for d in sorted(documents, key=lambda d: d.pk))
    if len(key) > 100:
        key = f'uploaded:{documents[0].pk}-{documents[-1].pk}:{len(documents)}'
    return notify_qa_staff(message, category='upload', link=link, dedupe_key=key, exclude=uploader)

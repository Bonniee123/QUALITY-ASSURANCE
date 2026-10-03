"""Views for managing in-app notifications."""
from urllib.parse import quote, urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_POST

from accounts.decorators import repository_access_required
from .models import Notification

def _fallback_redirect():
    return redirect('documents:repository')


@login_required
@repository_access_required
@require_POST
def mark_read(request, pk):
    """Mark a single notification as read."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect(n.link) if n.link else _fallback_redirect()


@login_required
@repository_access_required
@require_POST
def mark_all_read(request):
    """Mark all of the current user's notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return _fallback_redirect()


@login_required
@repository_access_required
def open_notification(request, pk):
    """GET handler: mark as read and redirect to the linked page."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    if not n.link:
        return _fallback_redirect()
    gone = _deleted_document_behind(n.link)
    if gone is not None:
        # The notification outlived its document. Say so, and for staff open
        # the record of what happened to it, instead of a "page not found".
        from accounts.permissions import is_admin
        messages.info(request, f'“{gone.title}” has since been deleted.')
        if is_admin(request.user):
            return redirect(f"{reverse('accounts:document_history')}?q={quote(gone.title[:80])}")
        return _fallback_redirect()
    return redirect(n.link)


def _deleted_document_behind(link):
    """The document a notification links to, if it has been deleted since; else None."""
    from documents.models import Document

    try:
        match = resolve(urlparse(link).path)
    except Resolver404:
        return None
    pk = match.kwargs.get('pk')
    if match.namespace != 'documents' or pk is None:
        return None
    doc = Document.objects.filter(pk=pk).only('pk', 'title', 'deleted_at').first()
    if doc is None:
        return Document(title='That document')
    return doc if doc.deleted_at else None


@login_required
def dropdown(request):
    """The bell's list, re-rendered for the live poll when a notification arrives."""
    # The list and the unread count come from notifications_context, the same
    # place the page itself got them, so the two cannot disagree.
    return render(request, 'notifications/_dropdown.html')

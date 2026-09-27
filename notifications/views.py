"""Views for managing in-app notifications."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
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
    return redirect(n.link) if n.link else _fallback_redirect()

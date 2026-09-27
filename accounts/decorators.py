"""
Role-based access control decorators.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect

from .permissions import ROLE_ADMIN, ROLE_QA_STAFF, ROLE_FACULTY


def _is_ajax_request(request):
    """True for fetch/XHR or JSON requests, where a redirect + flash message
    would leak onto the next full page instead of being shown to the user."""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return True
    content_type = (request.content_type or '')
    if 'application/json' in content_type:
        return True
    accept = request.headers.get('accept', '')
    return 'application/json' in accept and 'text/html' not in accept


def _ensure_profile(user):
    """
    Return the user's profile, creating a default one on the fly if missing.
    """
    from .models import UserProfile
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': ROLE_ADMIN if user.is_superuser else ROLE_QA_STAFF,
                'status': 'active',
            },
        )
        return profile
    except AttributeError:
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': ROLE_ADMIN if user.is_superuser else ROLE_QA_STAFF,
                'status': 'active',
            },
        )
        return profile


def _log_permission_denied(request, view_name, allowed_roles):
    try:
        from documents.models import ActivityLog

        roles_label = ', '.join(allowed_roles)
        ActivityLog.objects.create(
            user=request.user,
            action='permission_denied',
            description=(
                f'Access denied to {view_name} '
                f'(requires: {roles_label})'
            ),
        )
    except Exception:
        pass


def _inactive_response(request):
    from django.contrib.auth import logout

    logout(request)
    messages.error(request, 'Your account has been deactivated. Contact the administrator.')
    return redirect('accounts:login')


def role_required(*allowed_roles):
    """
    Restrict view access to users with specific roles.
    Usage: @role_required('admin', 'qa_staff')
    """
    allowed = tuple(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            profile = _ensure_profile(request.user)
            if profile.status != 'active':
                return _inactive_response(request)

            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            if profile.role in allowed:
                return view_func(request, *args, **kwargs)

            _log_permission_denied(request, view_func.__name__, allowed)
            if _is_ajax_request(request):
                return JsonResponse(
                    {'error': 'You do not have permission to perform this action.'},
                    status=403,
                )
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('documents:repository')

        return wrapper

    return decorator


def admin_required(view_func):
    """Restrict access to Administrator role only."""
    return role_required(ROLE_ADMIN)(view_func)


def qa_staff_required(view_func):
    """Restrict access to QA Head and Administrator roles."""
    return role_required(ROLE_ADMIN, ROLE_QA_STAFF)(view_func)


def repository_access_required(view_func):
    """Allow Administrator, QA Head and Faculty (Faculty is area-scoped inside views)."""
    return role_required(ROLE_ADMIN, ROLE_QA_STAFF, ROLE_FACULTY)(view_func)


def faculty_required(view_func):
    """Restrict access to Faculty (and Administrator for oversight)."""
    return role_required(ROLE_ADMIN, ROLE_FACULTY)(view_func)

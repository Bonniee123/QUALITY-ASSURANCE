"""
Views for authentication and user management.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from datetime import datetime, time
from urllib.parse import urlencode

from .forms import DepartmentForm, LoginForm, UserCreateForm, UserEditForm
from .models import Department, UserProfile
from .decorators import admin_required
from .permissions import ROLE_ADMIN, get_user_role
from .presence import presence
from .auth_security import (
    clear_login_attempts,
    is_login_locked,
    lockout_message,
    log_successful_login,
    record_failed_login,
)
from documents.models import ActivityLog, BackgroundJob
from documents.audit import distinct_logged_actions, log_activity


def _is_deactivated_account(username, password):
    """True if these are the right credentials for an account that is switched off."""
    from .auth_backends import resolve_login_name

    # Resolved the same way the backend resolves it, so somebody signing in
    # with their email address is told their account is deactivated rather
    # than that their password is wrong.
    try:
        account = User._default_manager.get_by_natural_key(resolve_login_name(username))
    except User.DoesNotExist:
        return False
    return not account.is_active and account.check_password(password)


def _post_login_redirect(user):
    """Role-based post-login landing."""
    return redirect('dashboard:home')


def home_redirect(request):
    """Send visitors to login, or dashboard when already signed in."""
    if request.user.is_authenticated:
        return redirect('dashboard:home')
    return redirect('accounts:login')


@sensitive_post_parameters('password')
@never_cache
def login_view(request):
    """
    Handle user login with rate limiting and audit logging.

    Never cached, as Django's own LoginView is: a stored copy is what the
    browser shows on Back after signing in -- the button still greyed out on
    "Signing in", and no request made that could have sent a signed-in visitor
    on to their dashboard, which is what this view does for them below.
    """
    if request.user.is_authenticated:
        return _post_login_redirect(request.user)

    form = LoginForm()
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            if is_login_locked(request, username):
                messages.error(request, lockout_message())
                return render(request, 'accounts/login.html', {'form': form})

            user = authenticate(request, username=username, password=password)
            if user is None and _is_deactivated_account(username, password):
                # Django's backend refuses an inactive account before this view
                # sees it, so the message below was never shown and a
                # deactivated user was told their password was wrong. Said only
                # to someone who has just proved the password.
                record_failed_login(request, username)
                messages.error(request, 'Your account has been deactivated. Contact the administrator.')
                return render(request, 'accounts/login.html', {'form': form})
            if user is not None:
                if hasattr(user, 'profile') and user.profile.status == 'inactive':
                    record_failed_login(request, username)
                    messages.error(request, 'Your account has been deactivated. Contact the administrator.')
                    return render(request, 'accounts/login.html', {'form': form})

                clear_login_attempts(request, username)
                login(request, user)
                request.session['_auth_last_activity'] = timezone.now().timestamp()
                log_successful_login(user, request)
                messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
                next_url = request.GET.get('next') or request.POST.get('next')
                # Django's own check, not a prefix test: "/\evil.example" passed
                # the old one, and browsers read it as "//evil.example".
                if next_url and url_has_allowed_host_and_scheme(
                        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return _post_login_redirect(user)

            remaining = record_failed_login(request, username)
            if remaining <= 0:
                messages.error(request, lockout_message())
            else:
                messages.error(request, 'Invalid username or password.')
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """
    Log out the current user -- on POST only.

    Signing out used to work by loading the URL, so an image or link on any
    other page could sign people out. The Log Out button posts a form; a GET
    changes nothing and goes back to where a signed-in user belongs.
    """
    if request.method != 'POST':
        return redirect('dashboard:home' if request.user.is_authenticated else 'accounts:login')
    if request.user.is_authenticated:
        ActivityLog.objects.create(
            user=request.user,
            action='logout',
            description=f'{request.user.username} logged out.'
        )
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('accounts:login')


@login_required
@admin_required
def user_list(request):
    """
    Display all users for admin management, active accounts first.

    "Active" here means the account is allowed to sign in, which is what
    profile.status controls; it does not mean the person is online right now.
    Accounts that can still be used are the ones an administrator acts on, so
    they are listed before deactivated ones. Within each group the newest
    account comes first, which is the order the page used before.
    """
    users = (User.objects
             .select_related('profile')
             .annotate(is_enabled=Case(
                 When(profile__status='active', then=Value(0)),
                 default=Value(1),
                 output_field=IntegerField(),
             ))
             .order_by('is_enabled', '-date_joined'))

    # Role filter. The value is checked against the roles the UserProfile model
    # actually defines rather than passed to the query as it arrives, so an
    # unknown or hand-edited ?role= shows everybody instead of an empty table
    # that looks like the accounts have gone.
    role_counts = {
        row['profile__role']: row['n']
        for row in User.objects.values('profile__role').annotate(n=Count('id'))
    }
    # The chips are read beside the role badges in the table below them, so they
    # use the same words: the model's own label for 'admin' is "Admin" while
    # every badge on the page says "Administrator".
    chip_labels = {'admin': 'Administrator'}
    role_filters = [
        {'value': '', 'label': 'All roles', 'count': sum(role_counts.values())},
    ] + [
        {'value': value, 'label': chip_labels.get(value, label),
         'count': role_counts.get(value, 0)}
        for value, label in UserProfile.ROLE_CHOICES
    ]
    valid_roles = {value for value, _label in UserProfile.ROLE_CHOICES}
    selected_role = (request.GET.get('role') or '').strip()
    if selected_role not in valid_roles:
        selected_role = ''
    if selected_role:
        users = users.filter(profile__role=selected_role)

    now = timezone.now()
    users = list(users)
    for u in users:
        u.presence = presence(u, now)
    return render(request, 'accounts/user_list.html', {
        'users': users,
        'role_filters': role_filters,
        'selected_role': selected_role,
        'total_user_count': sum(role_counts.values()),
    })


@login_required
@admin_required
@never_cache
def user_presence(request):
    """Online / offline for every account, polled by User Management to stay current."""
    now = timezone.now()
    return JsonResponse({
        'users': {str(u.pk): presence(u, now) for u in User.objects.select_related('profile')},
    })


@login_required
@admin_required
def user_create(request):
    """Create a new user account."""
    if request.method == 'POST':
        form = UserCreateForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            # Update profile with role, department and contact details
            user.profile.role = form.cleaned_data['role']
            user.profile.department = form.cleaned_data.get('department', '')
            user.profile.phone = form.cleaned_data.get('phone', '')
            avatar = form.cleaned_data.get('avatar')
            if avatar:
                user.profile.avatar = avatar
            user.profile.save()
            if form.cleaned_data['role'] == 'faculty':
                user.profile.assigned_areas.set(form.cleaned_data.get('assigned_areas') or [])
            else:
                user.profile.assigned_areas.clear()
            ActivityLog.objects.create(
                user=request.user,
                action='create_user',
                description=f'Created user: {user.username} with role {user.profile.get_role_display()}'
            )
            messages.success(request, f'User "{user.username}" created successfully.')
            return redirect('accounts:user_detail', pk=user.pk)
    else:
        form = UserCreateForm()
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'action': 'Create',
    })


def _refuse_self_lockout(request, user_obj, form):
    """
    True, with the reasons on the form, if this change would lock an
    Administrator out of their own account: removing their own Administrator
    role, deactivating themselves, or turning off their own sign-in.

    Only an active Administrator can reach these pages, so refusing it on your
    own account also means the last active Administrator cannot be removed.
    """
    if user_obj.pk != request.user.pk:
        return False
    data = form.cleaned_data
    refused = False
    if not user_obj.is_superuser and get_user_role(user_obj) == ROLE_ADMIN and data.get('role') != ROLE_ADMIN:
        form.add_error('role', 'You cannot remove your own Administrator role. Ask another Administrator to change it.')
        refused = True
    if data.get('status') == 'inactive':
        form.add_error('status', 'You cannot deactivate your own account.')
        refused = True
    if 'is_active' in data and not data['is_active']:
        form.add_error(None, 'You cannot turn off sign-in for your own account.')
        refused = True
    return refused


@login_required
@admin_required
def user_edit(request, pk):
    """Edit an existing user account."""
    user_obj = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=user_obj)
        if form.is_valid() and not _refuse_self_lockout(request, user_obj, form):
            form.save()
            # Update profile
            user_obj.profile.role = form.cleaned_data['role']
            user_obj.profile.department = form.cleaned_data.get('department', '')
            user_obj.profile.status = form.cleaned_data['status']
            user_obj.profile.phone = form.cleaned_data.get('phone', '')
            avatar = form.cleaned_data.get('avatar')
            if avatar:
                user_obj.profile.avatar = avatar
            user_obj.profile.save()
            if form.cleaned_data['role'] == 'faculty':
                user_obj.profile.assigned_areas.set(form.cleaned_data.get('assigned_areas') or [])
            else:
                user_obj.profile.assigned_areas.clear()

            new_password = form.cleaned_data.get('new_password')
            if new_password:
                user_obj.set_password(new_password)
                user_obj.save(update_fields=['password'])
                ActivityLog.objects.create(
                    user=request.user,
                    action='reset_password',
                    description=f'Reset password for user: {user_obj.username}'
                )

            ActivityLog.objects.create(
                user=request.user,
                action='edit_user',
                description=f'Updated user: {user_obj.username}'
            )
            # Names the person rather than quoting their username, and says so
            # when the password was reset as well -- that is the part of a save
            # an administrator most needs confirmed, and it was not mentioned.
            saved_name = user_obj.get_full_name() or user_obj.username
            if new_password:
                messages.success(
                    request,
                    f'Changes to {saved_name}’s account were saved, '
                    'and their password was reset.'
                )
            else:
                messages.success(request, f'Changes to {saved_name}’s account were saved.')
            return redirect('accounts:user_detail', pk=user_obj.pk)
    else:
        form = UserEditForm(instance=user_obj, initial={
            'role': user_obj.profile.role,
            'department': user_obj.profile.department,
            'status': user_obj.profile.status,
            'phone': user_obj.profile.phone,
        })
    display_name = user_obj.get_full_name() or user_obj.username
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'action': 'Edit',
        'user_obj': user_obj,
    })


@login_required
@admin_required
def user_detail(request, pk):
    """Read-only profile view for an individual user account."""
    user_obj = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    recent_activity = ActivityLog.objects.filter(user=user_obj).order_by('-created_at')[:10]
    display_name = user_obj.get_full_name() or user_obj.username
    return render(request, 'accounts/user_detail.html', {
        'user_obj': user_obj,
        'recent_activity': recent_activity,
    })


@login_required
@admin_required
def user_delete(request, pk):
    """Delete a user account."""
    user_obj = get_object_or_404(User, pk=pk)
    if user_obj.pk == request.user.pk:
        # Deleting yourself also failed with a server error: the audit entry was
        # written for a user who no longer existed.
        messages.error(request, 'You cannot delete your own account. Ask another Administrator to remove it.')
        return redirect('accounts:user_detail', pk=user_obj.pk)
    if request.method == 'POST':
        username = user_obj.username
        user_obj.delete()
        ActivityLog.objects.create(
            user=request.user,
            action='delete_user',
            description=f'Deleted user: {username}'
        )
        messages.success(request, f'User "{username}" deleted successfully.')
        return redirect('accounts:user_list')
    return render(request, 'accounts/user_confirm_delete.html', {
        'user_obj': user_obj,
    })


def _ai_engine_status():
    """
    Report the real availability of each engine shown on the Settings page.

    Four of these badges were hardcoded to "Online" in the template, so the page
    claimed the AI stack was up even where scikit-learn was missing. Each entry is
    probed now.
    """
    import importlib.util

    def _importable(module):
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    sklearn_ok = _importable('sklearn')

    # pytesseract being importable only proves the Python wrapper is present; OCR
    # also needs the Tesseract binary itself, so ask it for its version.
    ocr_ok = False
    if _importable('pytesseract'):
        try:
            import pytesseract
            from django.conf import settings as dj_settings

            cmd = (getattr(dj_settings, 'TESSERACT_CMD', '') or '').strip()
            if cmd:
                pytesseract.pytesseract.tesseract_cmd = cmd
            pytesseract.get_tesseract_version()
            ocr_ok = True
        except Exception:
            ocr_ok = False

    # Installed is not the same as working: the analysis engines also report how
    # their latest run went, and one that failed reads "Degraded" -- a run that
    # died of MemoryError used to leave every badge on "Online".
    last_run, degraded = _last_analysis_run()
    engines = [
        {'name': 'TF-IDF Analysis Engine', 'icon': 'bi-diagram-3',
         'desc': 'Extracts keyword signatures and semantic vectors', 'online': sklearn_ok},
        {'name': 'K-Means Clustering', 'icon': 'bi-bounding-box',
         'desc': 'Automatically groups related documents', 'online': sklearn_ok},
        {'name': 'Elbow Method Optimizer', 'icon': 'bi-graph-up',
         'desc': 'Charts the Elbow curve; each group\'s k is chosen by silhouette score, '
                 'with the Elbow as the fallback', 'online': sklearn_ok},
        {'name': 'Duplicate Prevention', 'icon': 'bi-shield-check',
         'desc': 'SHA-256 exact copies, text similarity (SequenceMatcher and TF-IDF cosine) '
                 'and look-alike images (dHash)', 'online': sklearn_ok},
    ]
    for engine in engines:
        engine['last_run'] = last_run
        engine['degraded'] = degraded
    engines.append(
        {'name': 'Tesseract OCR Engine', 'icon': 'bi-upc-scan',
         'desc': 'Optical character recognition for images and scans', 'online': ocr_ok,
         'last_run': 'Checked now: the Tesseract program answered.' if ocr_ok
         else 'Checked now: the Tesseract program was not found.', 'degraded': False},
    )
    return engines


def _last_analysis_run():
    """('Last run ... - completed/failed' text, failed?) for the latest analysis run."""
    job = (BackgroundJob.objects.filter(job_type='full_ai_pipeline', status__in=('completed', 'failed'))
           .order_by('-finished_at', '-pk').first())
    if job is None:
        return 'No analysis run yet.', False
    when = timezone.localtime(job.finished_at).strftime('%b %d, %Y %H:%M') if job.finished_at else 'unknown time'
    if job.status == 'failed':
        return f'Last run {when} failed: {(job.error or "no details")[:80]}', True
    return f'Last run {when} - completed.', False


@login_required
@admin_required
def settings_view(request):
    """System settings page."""
    log_activity(request, 'view_settings', 'Viewed system settings page.')
    from django.conf import settings as dj_settings

    engines = _ai_engine_status()
    max_bytes = getattr(dj_settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 25 * 1024 * 1024)
    return render(request, 'accounts/settings.html', {
        'ai_engines': engines,
        'ocr_enabled': engines[-1]['online'],
        # The template used to hardcode "25 MB"; show the configured limit instead.
        'max_upload_mb': max_bytes // (1024 * 1024),
    })


@login_required
@admin_required
def audit_log(request):
    """Administrator audit trail with filters."""
    qs = ActivityLog.objects.select_related('user').order_by('-created_at')

    q = request.GET.get('q', '').strip()
    action = request.GET.get('action', '').strip()
    user_id = request.GET.get('user', '').strip()
    date_from = request.GET.get('from', '').strip()
    date_to = request.GET.get('to', '').strip()

    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(user__username__icontains=q))
    if action:
        qs = qs.filter(action=action)
    if user_id.isdigit():
        qs = qs.filter(user_id=int(user_id))
    if date_from:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d').date()
            qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min)))
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.strptime(date_to, '%Y-%m-%d').date()
            qs = qs.filter(created_at__lte=timezone.make_aware(datetime.combine(end, time.max)))
        except ValueError:
            pass

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_params = {}
    if q:
        filter_params['q'] = q
    if action:
        filter_params['action'] = action
    if user_id:
        filter_params['user'] = user_id
    if date_from:
        filter_params['from'] = date_from
    if date_to:
        filter_params['to'] = date_to

    return render(request, 'accounts/audit_log.html', {
        'page_obj': page_obj,
        'action_choices': distinct_logged_actions(),
        'user_choices': User.objects.order_by('username'),
        'filters': {
            'q': q,
            'action': action,
            'user_id': user_id,
            'date_from': date_from,
            'date_to': date_to,
        },
        'query_string': urlencode(filter_params),
    })


@login_required
@admin_required
def document_history(request):
    """
    Every document ever archived, including deleted ones, with who uploaded
    and who deleted it and its full history.

    The rows are documents, not log entries: "what happened to this file" is
    the question, and a deleted document stays listed -- with the name it had,
    who removed it and when -- after its file is gone.
    """
    from django.db.models import Prefetch, prefetch_related_objects

    from documents.audit import DOCUMENT_EVENT_ACTIONS
    from documents.deletion import finalize_expired_batches
    from documents.models import DeletionBatch, Document

    finalize_expired_batches()
    now = timezone.now()
    qs = Document.objects.select_related('uploaded_by', 'deleted_by', 'deletion_batch', 'acc_area')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    uploader = request.GET.get('uploader', '').strip()
    deleter = request.GET.get('deleter', '').strip()

    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(original_filename__icontains=q)
            | Q(uploaded_by__username__icontains=q) | Q(uploaded_by__first_name__icontains=q)
            | Q(uploaded_by__last_name__icontains=q) | Q(deleted_by__username__icontains=q)
            | Q(deleted_by__first_name__icontains=q) | Q(deleted_by__last_name__icontains=q)
            | Q(deletion_batch__user_name__icontains=q)
        )
    pending = Q(deleted_at__isnull=False, purged_at__isnull=True,
                deletion_batch__status=DeletionBatch.STATUS_PENDING, deletion_batch__expires_at__gt=now)
    if status == 'active':
        qs = qs.filter(deleted_at__isnull=True)
    elif status == 'pending':
        qs = qs.filter(pending)
    elif status == 'deleted':
        qs = qs.filter(deleted_at__isnull=False)
    elif status == 'purged':
        qs = qs.filter(purged_at__isnull=False)
    elif status == 'restored':
        qs = qs.filter(deleted_at__isnull=True, activity__action='restore_document').distinct()
    else:
        status = ''
    if uploader.isdigit():
        qs = qs.filter(uploaded_by_id=int(uploader))
    if deleter.isdigit():
        qs = qs.filter(deleted_by_id=int(deleter))

    # Deleted documents first, newest change first: what someone opens this
    # page to check is usually what just disappeared.
    qs = qs.order_by(Coalesce('deleted_at', 'uploaded_at').desc(), '-pk')
    page_obj = Paginator(qs, 25).get_page(request.GET.get('page'))
    rows = list(page_obj.object_list)
    events = Prefetch(
        'activity',
        queryset=ActivityLog.objects.filter(action__in=DOCUMENT_EVENT_ACTIONS).select_related('user', 'batch').order_by('created_at', 'pk'),
        to_attr='history',
    )
    prefetch_related_objects(rows, events)

    counts = Document.objects.aggregate(
        total=Count('pk'),
        active=Count('pk', filter=Q(deleted_at__isnull=True)),
        deleted=Count('pk', filter=Q(deleted_at__isnull=False)),
        purged=Count('pk', filter=Q(purged_at__isnull=False)),
    )
    filter_params = {k: v for k, v in (('q', q), ('status', status), ('uploader', uploader), ('deleter', deleter)) if v}
    people = User.objects.order_by('first_name', 'last_name', 'username')

    return render(request, 'accounts/document_history.html', {
        'page_obj': page_obj,
        'rows': rows,
        'counts': counts,
        'filters': {'q': q, 'status': status, 'uploader': uploader, 'deleter': deleter},
        'status_choices': [
            ('active', 'Active'), ('pending', 'Deleted — undo available'), ('deleted', 'Deleted (all)'),
            ('purged', 'Permanently deleted'), ('restored', 'Restored after a delete'),
        ],
        'uploader_choices': people.filter(pk__in=Document.objects.values('uploaded_by')),
        'deleter_choices': people.filter(pk__in=Document.objects.filter(deleted_by__isnull=False).values('deleted_by')),
        'query_string': urlencode(filter_params),
    })


@login_required
@admin_required
@require_POST
def department_quick_add(request):
    """
    Create a department from the account form and return it as JSON.

    The full management page exists for editing and removing, but adding one
    should not cost the Administrator the half-filled account form they are
    standing in. This accepts the name alone, creates the row, and hands back
    what the dropdown needs to show it as selected.

    An existing name is not an error here. The caller wanted that department to
    be available and now it is, so the row is returned as though it had just
    been created and the dropdown selects it either way.
    """
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'ok': False, 'error': 'Enter a department or office name.'}, status=400)
    if len(name) > 100:
        return JsonResponse({'ok': False, 'error': 'Use 100 characters or fewer.'}, status=400)

    existing = Department.objects.filter(name__iexact=name).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=['is_active'])
        return JsonResponse({'ok': True, 'name': existing.name, 'created': False})

    dept = Department.objects.create(name=name)
    ActivityLog.objects.create(
        user=request.user,
        action='create_department',
        description=f'Created department from the account form: {dept.name}',
    )
    return JsonResponse({'ok': True, 'name': dept.name, 'created': True})


@login_required
@admin_required
def department_quick_list(request):
    """
    The department list as JSON, for the panel on the account form.

    Carries the account count for each one so the panel can warn before a
    delete that would leave people showing a department nobody maintains.
    """
    rows = [
        {'id': d.pk, 'name': d.name, 'members': d.member_count}
        for d in Department.objects.filter(is_active=True).order_by('name')
    ]
    return JsonResponse({'ok': True, 'departments': rows})


@login_required
@admin_required
@require_POST
def department_quick_delete(request, pk):
    """
    Remove a department from the dropdown, from the account form.

    Accounts recording this department are untouched: the profile stores the
    name as text, not a link to this row, so nobody is edited and nobody loses
    access. The reply reports how many accounts still show the name, which the
    panel passes on rather than leaving the Administrator to guess.
    """
    dept = get_object_or_404(Department, pk=pk)
    name = dept.name
    members = dept.member_count
    dept.delete()
    ActivityLog.objects.create(
        user=request.user,
        action='delete_department',
        description=f'Deleted department from the account form: {name} '
                    f'({members} account(s) still record it)',
    )
    return JsonResponse({'ok': True, 'name': name, 'members': members})


@login_required
@admin_required
@require_POST
def user_toggle_active(request, pk):
    """
    Turn an account's access on or off from the user table.

    Two switches block a sign-in: Django's own is_active, which its
    authentication backend refuses before the login view runs, and
    profile.status, which the login view checks afterwards. They are set
    together here. Driving only one would leave an account reading "Active" in
    the table while the other switch still refused the password, and the person
    would be told their account was deactivated with nothing on screen to
    explain why.

    An Administrator cannot switch off their own access, matching the same
    refusal on the edit form; locking yourself out needs another Administrator
    to undo.
    """
    account = get_object_or_404(User, pk=pk)

    if account.pk == request.user.pk:
        return JsonResponse(
            {'ok': False, 'error': 'You cannot turn off your own access.'}, status=400)

    turning_on = not (account.is_active and account.profile.status == 'active')

    account.is_active = turning_on
    account.save(update_fields=['is_active'])
    account.profile.status = 'active' if turning_on else 'inactive'
    account.profile.save(update_fields=['status'])

    ActivityLog.objects.create(
        user=request.user,
        action='activate_user' if turning_on else 'deactivate_user',
        description=('Activated account: ' if turning_on else 'Deactivated account: ')
                    + account.username,
    )
    return JsonResponse({
        'ok': True,
        'active': turning_on,
        'username': account.username,
    })

"""
Views for direct messaging.

Access rule, in one line: **you may read and write a thread only if you are one of
its participants.** Everything else -- who may start a conversation with whom, what
may be said -- is deliberately unrestricted.

A non-participant asking for a thread gets 404 rather than 403. Confirming that a
thread exists between two named people is itself information, so the safe answer is
that it does not exist as far as this caller is concerned.

Every view here is ``@never_cache``. What these endpoints return is not a fact
about a thread, it is a fact about a thread *as seen by one account*: whether a
message is "mine" is computed against the caller. Django sets ``Vary: Cookie``
but no ``Cache-Control``, and a response with no freshness directive may be
cached heuristically -- so a reply built for one signed-in user could be replayed
to the next, showing them the other person's messages as their own.
"""
import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from documents.audit import log_activity
from documents.models import Document

from accounts.avatars import avatar_url as _profile_photo
from accounts.middleware import is_passive_request
from .area_search import area_codes_for
from .models import Thread, ThreadMessage


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _matched_label(codes, areas) -> str:
    """The searched area if this person is in it, else all their areas."""
    wanted = {a.area_code for a in areas}
    hit = [c for c in codes if c in wanted]
    return ', '.join(hit or codes)


def _areas_matching(query: str) -> list:
    """
    Accreditation areas the query names, by code, number or area name.

    "Area #5", "Area 5", "5" and "Area V" all resolve through
    ``area_codes_for``; the area's own name ("Research") is matched here because
    that needs the database. A short fragment is not treated as a name match --
    two characters would pull in most of the list and make the result look random.
    """
    from qa_structure.models import AccreditationArea

    query = (query or '').strip()
    if not query:
        return []

    condition = Q()
    codes = area_codes_for(query)
    if codes:
        condition |= Q(area_code__in=codes)
    if len(query) >= 3:
        condition |= Q(area_name__icontains=query)
    if not condition:
        return []
    return list(AccreditationArea.objects.filter(condition))


def _users_in_areas(areas):
    """Active users assigned to any of these areas."""
    return (User.objects.select_related('profile')
            .filter(is_active=True, profile__assigned_areas__in=areas)
            .distinct())


def _area_labels(user) -> list:
    profile = getattr(user, 'profile', None)
    if not profile:
        return []
    return list(profile.assigned_areas.values_list('area_code', flat=True))


def _name_q(query: str, prefix: str = '') -> Q:
    """
    Match a person by any part of the name they are displayed under.

    People appear in the interface by full name, so the natural thing to type is
    the full name -- but no single column holds it: ``qahead`` is stored as
    first_name 'QA', last_name 'Head'. A plain ``icontains`` over each column
    therefore found nothing for "QA Head", which is what made the search look
    like it could not see most of the roster.

    Each whitespace-separated token must match one of the name columns, so
    "QA Head" and "Head QA" both resolve, a single token still behaves as an
    ordinary substring search, and an extra word narrows rather than widens.
    """
    fields = ('first_name', 'last_name', 'username')
    combined = Q()
    for token in query.split():
        token_q = Q()
        for field in fields:
            token_q |= Q(**{f'{prefix}{field}__icontains': token})
        combined &= token_q
    return combined


def _thread_for(request, pk) -> Thread:
    """A thread the caller participates in, or 404."""
    return get_object_or_404(Thread, pk=pk, participants=request.user)


def _display(user) -> str:
    if user is None:
        return 'Deleted user'
    return user.get_full_name() or user.get_username()


def _role_of(user) -> str:
    profile = getattr(user, 'profile', None)
    if not profile:
        return ''
    return {'admin': 'Administrator', 'qa_staff': 'QA Head',
            'faculty': 'Faculty'}.get(profile.role, profile.role)


def _initials(user) -> str:
    name = _display(user)
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def _avatar(user) -> str:
    """
    The account's own profile photo URL, or '' when it has none.

    Always called with the person the payload is *about* -- a thread's other
    participant, a message's stored sender, a row in the roster -- never with
    the account doing the reading. That is what keeps a sender's face on their
    own message no matter who opens the conversation.
    """
    return _profile_photo(user)


def _other_read_upto(thread: Thread, viewer) -> int:
    """Id of the last message the other participant has read (0 for none)."""
    state = (thread.read_states.exclude(user=viewer)
             .order_by('-last_read_message_id').first())
    return state.last_read_message_id if state else 0


def _first_unread_id(thread: Thread, viewer):
    """Id of the earliest message this reader has not seen, or None."""
    state = thread.read_states.filter(user=viewer).first()
    qs = thread.visible_messages().exclude(sender=viewer)
    if state:
        qs = qs.filter(pk__gt=state.last_read_message_id)
    first = qs.order_by('id').first()
    return first.pk if first else None


def _thread_json(thread: Thread, viewer) -> dict:
    other = thread.other_participant(viewer)
    last = thread.last_message()
    preview = ''
    if last:
        who = 'You: ' if last.sender_id == viewer.pk else ''
        preview = who + (last.body[:70] if last.body else 'Shared a document')
    return {
        'id': thread.pk,
        'name': _display(other),
        'role': _role_of(other),
        'initials': _initials(other),
        'avatar': _avatar(other),
        # Carried so an area search can label an existing conversation with the
        # area too, instead of only the people who have no thread yet.
        'areas': _area_labels(other) if other else [],
        'preview': preview,
        'updated': thread.updated_at.strftime('%b %d, %H:%M'),
        'unread': thread.unread_count_for(viewer),
    }


def _message_json(message: ThreadMessage, viewer, other_read_upto=0) -> dict:
    # The sender is the stored sender_id, compared against the account that
    # asked. Never the position of the message, the sender's role, or which side
    # of the conversation is being viewed.
    mine = message.sender_id is not None and message.sender_id == viewer.pk
    payload = {
        'id': message.pk,
        'mine': mine,
        # Both ids travel with the message so the interface can decide for
        # itself rather than trusting a flag it cannot check. A payload built
        # for someone else is then detectable instead of being rendered.
        'sender_id': message.sender_id,
        'viewer_id': viewer.pk,
        'sender': _display(message.sender),
        'initials': _initials(message.sender),
        # Resolved from message.sender -- the account that actually sent this
        # message -- so every bubble carries its own author's face. Reading the
        # viewer here would stamp the reader's photo on the whole conversation.
        'avatar': _avatar(message.sender),
        'body': message.body,
        'time': message.created_at.strftime('%H:%M'),
        # The full stamp is sent as well so the interface can show an absolute
        # date on hover without a second request.
        'iso': message.created_at.isoformat(),
        'stamp': message.created_at.strftime('%b %d, %Y at %H:%M'),
        'edited': bool(message.edited_at),
        # Whether the other participant has read up to this message. Only
        # meaningful for your own messages -- it is the read receipt.
        'read': bool(mine and message.pk <= other_read_upto),
        'document': None,
        'document_withheld': False,
    }
    if message.document_id:
        visible = message.visible_document_for(viewer)
        if visible is not None:
            from django.urls import reverse
            payload['document'] = {
                'id': visible.pk,
                'title': visible.title,
                'year': visible.year,
                'area': (visible.acc_area.area_code if visible.acc_area_id
                         else visible.qa_area),
                'view_url': reverse('documents:view', args=[visible.pk]),
            }
        else:
            # The sender attached something this reader may not open. Say so
            # plainly rather than leaking the title through a broken link.
            payload['document_withheld'] = True
    return payload


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@login_required
@never_cache
def inbox(request):
    """The messages workspace."""
    return render(request, 'messaging/inbox.html', {
    })


# --------------------------------------------------------------------------- #
# Threads
# --------------------------------------------------------------------------- #

def _filter_threads(threads, query: str, viewer):
    """
    Narrow a thread queryset by what was typed.

    Matches on the other person's name, on the area they are assigned to, or on
    anything said in the thread. The people are resolved first and the caller is
    excluded: searching your own name would otherwise match every thread you are
    in, and each one is listed under the *other* participant's name, so the
    result looked arbitrary.
    """
    areas = _areas_matching(query)
    if areas:
        # "Area 5" should also surface conversations already open with the
        # people in it, not push them into the new-contact list.
        people = _users_in_areas(areas)
    else:
        people = User.objects.filter(_name_q(query))
    matches = people.exclude(pk=viewer.pk).values_list('pk', flat=True)
    return threads.filter(
        Q(participants__in=list(matches))
        | Q(messages__body__icontains=query)
    ).distinct()


@login_required
@never_cache
def thread_list(request):
    query = (request.GET.get('q') or '').strip()
    threads = (Thread.objects.filter(participants=request.user)
               .prefetch_related('participants__profile', 'read_states'))
    if query:
        threads = _filter_threads(threads, query, request.user)
    return JsonResponse({
        'threads': [_thread_json(t, request.user) for t in threads[:60]],
    })


@login_required
@never_cache
def thread_detail(request, pk):
    thread = _thread_for(request, pk)
    # Capture the unread mark *before* clearing it, so the interface can draw a
    # "new messages" divider at the point the reader last left off.
    first_unread = _first_unread_id(thread, request.user)
    messages = list(thread.visible_messages()
                    .select_related('sender__profile', 'document').order_by('id'))
    # Read up to the last message this response delivers, not whatever is
    # newest by the time the mark is written.
    if messages:
        thread.mark_read_for(request.user, upto=messages[-1].pk)
    other_read_upto = _other_read_upto(thread, request.user)
    return JsonResponse({
        'thread': _thread_json(thread, request.user),
        'messages': [_message_json(m, request.user, other_read_upto) for m in messages],
        'first_unread': first_unread,
    })


@login_required
@require_POST
def thread_start(request):
    """Open (or reopen) a conversation with a specific person."""
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = request.POST
    try:
        other = User.objects.select_related('profile').get(pk=int(data.get('user_id')))
    except (User.DoesNotExist, TypeError, ValueError):
        return JsonResponse({'error': 'No such user.'}, status=404)

    if other.pk == request.user.pk:
        return JsonResponse({'error': 'You cannot message yourself.'}, status=400)
    profile = getattr(other, 'profile', None)
    if not other.is_active or (profile and profile.status == 'inactive'):
        return JsonResponse({'error': 'That account is deactivated.'}, status=400)

    thread, _created = Thread.get_or_create_between(request.user, other)
    return JsonResponse({'thread': _thread_json(thread, request.user)})


@login_required
@require_POST
def message_send(request, pk):
    thread = _thread_for(request, pk)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = request.POST

    body = (data.get('body') or '').strip()
    document_id = data.get('document_id')
    document = None
    if document_id:
        # The sender may only attach what they can open themselves. Whether the
        # recipient sees it is decided separately, when the message is rendered.
        from accounts.permissions import user_can_access_document
        candidate = Document.objects.filter(pk=document_id).first()
        if candidate and user_can_access_document(request.user, candidate):
            document = candidate

    if not body and document is None:
        return JsonResponse({'error': 'Message is empty.'}, status=400)

    message = ThreadMessage.objects.create(
        thread=thread, sender=request.user, body=body, document=document
    )
    thread.touch()
    thread.mark_read_for(request.user, upto=message.pk)

    _notify_recipients(thread, request.user, message)
    # No thread number, no recipient, no content. The row exists so the action
    # is accountable; naming the thread would publish who is talking to whom.
    log_activity(request, 'send_message', 'Sent a direct message.')

    return JsonResponse({'message': _message_json(message, request.user),
                         'thread': _thread_json(thread, request.user)})


@login_required
@require_POST
def message_delete(request, pk, message_id):
    """
    Soft delete. The sender may remove their own message.

    Nothing is destroyed: the row stays so a conversation cannot be silently
    rewritten after the fact.
    """
    thread = _thread_for(request, pk)
    message = get_object_or_404(ThreadMessage, pk=message_id, thread=thread,
                                sender=request.user)
    message.is_deleted = True
    message.save(update_fields=['is_deleted'])
    log_activity(request, 'delete_message', 'Deleted a direct message.')
    return JsonResponse({'deleted': message.pk})


# --------------------------------------------------------------------------- #
# People
# --------------------------------------------------------------------------- #

@login_required
@never_cache
def people(request):
    """
    Everyone who can be messaged.

    The whole roster, by design: a QA Head must be able to reach a named Faculty
    member and vice versa. Deactivated accounts are excluded because a message to
    them would never be read.
    """
    query = (request.GET.get('q') or '').strip()
    users = (User.objects.select_related('profile')
             .filter(is_active=True)
             .exclude(pk=request.user.pk))

    # An area reference is answered with that area's members and nothing else.
    # Mixing in name matches would list people who are not in the area, which is
    # the opposite of what the search was asked for.
    areas = _areas_matching(query) if query else []
    if areas:
        users = users.filter(pk__in=_users_in_areas(areas).values('pk'))
    elif query:
        users = users.filter(_name_q(query))

    rows = []
    for user in users.order_by('first_name', 'username')[:100]:
        profile = getattr(user, 'profile', None)
        if profile and profile.status == 'inactive':
            continue
        codes = _area_labels(user)
        rows.append({
            'id': user.pk,
            'name': _display(user),
            'role': _role_of(user),
            'initials': _initials(user),
            'avatar': _avatar(user),
            'areas': codes,
            # What to show beside the name. During an area search the matched
            # area is the useful label; otherwise the role is.
            'area_label': _matched_label(codes, areas) if areas else '',
        })
    # A query like "Area 11" names no real area, but it is plainly an area
    # reference: answering with the generic "nobody matches" would suggest the
    # search was not understood.
    looked_like_area = bool(query) and (bool(areas) or bool(area_codes_for(query)))
    return JsonResponse({
        'people': rows,
        'area_search': looked_like_area,
        'area_names': [f'{a.area_code} - {a.area_name}' for a in areas],
    })


@login_required
@never_cache
def sync(request):
    """
    Everything the interface needs to stay current, in one request.

    There are no WebSockets in this stack, so the page asks for changes on a
    short interval. Doing it through a single endpoint keeps that to one request
    per tick instead of three, and lets the server answer "nothing changed"
    cheaply.

    ``?counts=1`` returns just the two badge numbers -- that is what every other
    page polls, so the sidebar and the bell stay live without pulling the whole
    conversation list.
    """
    from notifications.models import Notification

    from .models import unread_total_for

    unread_messages = unread_total_for(request.user)
    unread_notifications = Notification.objects.filter(
        user=request.user, is_read=False).count()

    payload = {
        'unread_messages': unread_messages,
        'unread_notifications': unread_notifications,
    }

    if request.GET.get('counts'):
        return JsonResponse(payload)

    query = (request.GET.get('q') or '').strip()
    threads = (Thread.objects.filter(participants=request.user)
               .prefetch_related('participants__profile', 'read_states'))
    if query:
        threads = _filter_threads(threads, query, request.user)
    payload['threads'] = [_thread_json(t, request.user) for t in threads[:60]]

    # New messages in the conversation the reader currently has open.
    thread_id = request.GET.get('thread')
    after = request.GET.get('after')
    if thread_id:
        thread = (Thread.objects.filter(pk=thread_id, participants=request.user)
                  .first())
        if thread is not None:
            fresh = thread.visible_messages().select_related('sender__profile', 'document')
            try:
                on_screen = max(int(after or 0), 0)
            except (TypeError, ValueError):
                on_screen = 0
            if on_screen:
                fresh = fresh.filter(pk__gt=on_screen)
            other_read_upto = _other_read_upto(thread, request.user)
            rows = list(fresh.order_by('id')[:50])
            payload['messages'] = [
                _message_json(m, request.user, other_read_upto) for m in rows
            ]
            # Seeing them is reading them -- when someone is there to see them.
            # A passive refresh (nobody has touched the page for a minute) still
            # puts new messages on screen, but must not report them read: the
            # sender would be told "Read" while the screen sat unattended.
            #
            # Which means the first refresh after the reader is back has to mark
            # them, even though it brings nothing new -- the messages already
            # arrived during the passive one, so waiting for `rows` would leave
            # them unread for good while they sit in plain view.
            #
            # Only what is on the screen is marked: the messages this response
            # delivers, or those already shown (`after`). A message that lands
            # while this request runs stays unread until a refresh delivers it.
            if not is_passive_request(request):
                seen = rows[-1].pk if rows else on_screen
                if seen and thread.mark_read_for(request.user, upto=seen):
                    payload['unread_messages'] = unread_total_for(request.user)
            # Read receipts change without any new message arriving, so the
            # already-sent ones are reported too.
            payload['read_upto'] = other_read_upto or None
    return JsonResponse(payload)


@login_required
@never_cache
def unread_count(request):
    from .models import unread_total_for
    return JsonResponse({'unread': unread_total_for(request.user)})


# --------------------------------------------------------------------------- #
# Notification
# --------------------------------------------------------------------------- #

def _notify_recipients(thread: Thread, sender, message: ThreadMessage) -> None:
    """
    Tell everyone else that a message arrived: who sent it, not what it said.

    The notification used to carry the first ninety characters of the body, so
    the conversation could be read from the bell -- and every reply added
    another entry, which is what made the list run for screens. The words stay
    in Messages, one notification per conversation, and it links there.
    """
    try:
        from django.urls import reverse
        from django.utils import timezone

        from notifications.models import Notification
        from notifications.services import notify
        from notifications.user_messages import message_arrived_message

        recipients = list(thread.participants.exclude(pk=sender.pk))
        if not recipients:
            return
        link = f"{reverse('messaging:inbox')}?thread={thread.pk}"
        for recipient in recipients:
            text = message_arrived_message(
                _display(sender), thread.unread_count_for(recipient), bool(message.body),
            )
            standing = (Notification.objects
                        .filter(user=recipient, category='message', link=link, is_read=False)
                        .first())
            if standing:
                standing.message = text
                standing.created_at = timezone.now()
                standing.save(update_fields=['message', 'created_at'])
            else:
                notify(recipient, text, category='message', link=link)
    except Exception:  # pragma: no cover - a failed notification must not
        pass          # prevent the message itself from being delivered

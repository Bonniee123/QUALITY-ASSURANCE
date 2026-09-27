"""
Views for the QA Archive Agent.

The two original endpoints keep their behaviour -- ``chatbot_page`` renders a chat
page and ``chatbot_api`` answers a single message -- so every existing caller,
including the floating widget, works unchanged. What is new is thread
persistence: conversations, titles and messages, each scoped to the account that
owns them.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.decorators import repository_access_required
from qa_archiving_system import rate_limit

from .chatbot_rules import get_chatbot_response
from .models import Conversation, Message


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _owned(request, pk):
    """
    A conversation the caller owns.

    Anything else is a 404 rather than a 403: a thread quotes document titles,
    and confirming that someone else's thread exists would leak that much.
    """
    return get_object_or_404(Conversation, pk=pk, user=request.user, is_deleted=False)


def _serialise(conversation):
    return {
        'id': conversation.pk,
        'title': conversation.title,
        'preview': conversation.preview,
        'updated': conversation.updated_at.strftime('%b %d, %H:%M'),
        'messages': conversation.messages.count(),
    }


def _message_json(message):
    payload = message.payload or {}
    return {
        'id': message.pk,
        'role': message.role,
        'text': message.text,
        'cards': payload.get('cards') or [],
        'actions': payload.get('actions') or [],
        'note': payload.get('note') or '',
        'time': message.created_at.strftime('%H:%M'),
    }


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@login_required
@repository_access_required
def chatbot_page(request):
    """Render the agent workspace."""
    conversations = Conversation.objects.filter(user=request.user, is_deleted=False)[:50]
    return render(request, 'chatbot/chatbot.html', {
        'conversations': conversations,
    })


# --------------------------------------------------------------------------- #
# Messaging
# --------------------------------------------------------------------------- #

@login_required
@repository_access_required
def chatbot_api(request):
    """
    Answer one message.

    With a conversation id the turn is stored against that thread; without one
    the reply is simply returned, which is what the floating widget does.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)

    if not rate_limit.allow(request, 'chatbot'):
        # 'answer' is what both chat screens display; nothing is stored in the thread.
        return JsonResponse({
            'answer': ('You are sending messages too quickly '
                       f'(limit: {rate_limit.describe_limit("chatbot")}). '
                       'Please wait a moment and try again.'),
            'error': 'rate_limited',
        }, status=429)

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    user_message = (data.get('message') or request.POST.get('message') or '').strip()
    conversation_id = data.get('conversation_id') or request.POST.get('conversation_id')

    result = get_chatbot_response(user_message, request)

    conversation = None
    if conversation_id:
        try:
            conversation = _owned(request, int(conversation_id))
        except (ValueError, TypeError):
            conversation = None

    if conversation is None and data.get('start_conversation') and user_message:
        conversation = Conversation.objects.create(
            user=request.user, title=Conversation.title_from(user_message)
        )

    if conversation is not None and user_message:
        conversation.touch_title(user_message)
        conversation.save(update_fields=['title', 'updated_at'])
        Message.objects.create(conversation=conversation, role=Message.USER,
                               text=user_message)
        Message.objects.create(
            conversation=conversation, role=Message.AGENT,
            text=result.get('answer', ''),
            payload={
                'cards': result.get('cards') or [],
                'actions': result.get('actions') or [],
                'note': result.get('note') or '',
                'intent': result.get('intent') or '',
            },
        )
        result['conversation'] = _serialise(conversation)

    return JsonResponse(result)


# --------------------------------------------------------------------------- #
# Conversation management
# --------------------------------------------------------------------------- #

@login_required
@repository_access_required
def conversation_list(request):
    """The thread list, optionally filtered by a search term."""
    query = (request.GET.get('q') or '').strip()
    threads = Conversation.objects.filter(user=request.user, is_deleted=False)
    if query:
        threads = threads.filter(
            Q(title__icontains=query) | Q(messages__text__icontains=query)
        ).distinct()
    return JsonResponse({'conversations': [_serialise(c) for c in threads[:60]]})


@login_required
@repository_access_required
def conversation_detail(request, pk):
    conversation = _owned(request, pk)
    return JsonResponse({
        'conversation': _serialise(conversation),
        'messages': [_message_json(m) for m in conversation.messages.all()],
    })


@login_required
@repository_access_required
@require_POST
def conversation_create(request):
    conversation = Conversation.objects.create(user=request.user)
    return JsonResponse({'conversation': _serialise(conversation)})


@login_required
@repository_access_required
@require_POST
def conversation_rename(request, pk):
    conversation = _owned(request, pk)
    try:
        title = (json.loads(request.body or b'{}').get('title') or '').strip()
    except json.JSONDecodeError:
        title = (request.POST.get('title') or '').strip()
    if title:
        conversation.title = title[:120]
        conversation.save(update_fields=['title', 'updated_at'])
    return JsonResponse({'conversation': _serialise(conversation)})


@login_required
@repository_access_required
@require_POST
def conversation_delete(request, pk):
    """Soft delete, so a thread removed by mistake can still be recovered."""
    conversation = _owned(request, pk)
    conversation.is_deleted = True
    conversation.save(update_fields=['is_deleted', 'updated_at'])
    return JsonResponse({'deleted': pk})

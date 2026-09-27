# In-System Messaging — Design Plan

**Date:** 2026-09-08 (revised)
**Status:** design only. No code has been written and nothing in the system has changed.
**Requirement:** any user can message a specific person — a QA Head can message a named
Faculty member, and vice versa — inside the system.

---

## 1. Recommendation

**Build it.** Direct person-to-person messaging is the right feature for this system,
and the workflow already needs it.

Notifications flow one way today — duplicate alerts, bulk-upload results — through
`notifications.services.notify()` and the navbar bell. There is no reply. A QA Head
cannot ask a named Faculty member *"can you re-upload this under the correct area?"*,
and that person cannot answer. Today that exchange happens over chat apps or email,
which means the reasoning behind an accreditation decision lives outside the archive
it concerns.

### 1.1 A correction to my earlier advice

An earlier draft of this plan argued against person-to-person messaging on the grounds
that Faculty in different areas could paste document titles to each other and defeat
the area scoping. **That reasoning was overweighted and is withdrawn.**

Those people can already email, message or talk to each other. A system cannot prevent
a human disclosing something they legitimately know, and no messaging feature should be
designed as though it could. The access control that matters is on *documents*, and it
stays exactly where it is.

What *is* worth controlling is the one case where the system itself would do the
leaking — see §4.

---

## 2. Model

```
Thread                                  # a conversation between two people
    participants   M2M -> auth.User     (exactly two for a direct message)
    created_at     DateTimeField
    updated_at     DateTimeField        (bumped on each message; drives ordering)

ThreadMessage
    thread         FK -> Thread          (related_name='messages')
    sender         FK -> auth.User       (on_delete=SET_NULL, null=True)
    body           TextField
    document       FK -> documents.Document, null=True   # optional attachment
    created_at     DateTimeField
    edited_at      DateTimeField, null=True
    is_deleted     BooleanField(default=False)

ThreadRead                              # unread state, one row per participant
    thread         FK -> Thread
    user           FK -> auth.User
    last_read_at   DateTimeField
    unique_together = (thread, user)
```

Design notes:

* **`Thread` is generic, not hard-coded to two people.** Direct messages create a
  two-participant thread. If group discussion is wanted later it is the same model,
  which avoids a migration that rewrites history.
* **Unread lives in its own table, not a boolean on the message.** With a flag per
  message, marking a thread read is an UPDATE across every row; with `last_read_at`
  it is one row, and the unread count is a single `COUNT` with a timestamp compare.
* **Soft delete**, consistent with agent conversations and document archiving.
* **`document` is a real foreign key, not a pasted URL.** That is what makes §4
  possible.

---

## 3. Who may message whom

**Anyone may message anyone.** QA Head to a named Faculty member, Faculty to QA Head,
administrator to either, Faculty to Faculty. This is the requirement, and per §1.1
there is no good reason to restrict it.

The recipient picker lists active accounts with their display name and role, so a QA
Head choosing between *Faith Cruz (Faculty, Area II)* and *Marco Reyes (Faculty,
Area III)* picks the right person. The roster is small — nine accounts today — so a
simple searchable select is enough; no pagination needed.

One deliberate exclusion: **deactivated accounts cannot be started with**, though
existing threads with them stay readable. `UserProfile.status` already carries this.

---

## 4. The one real containment: attached documents

Plain text is plain text and the system will not police it. But a message can carry a
**document reference**, and that reference is rendered by the system — so the system
must not hand someone a document they cannot open.

> A document attached to a message is resolved **per reader**, at render time, through
> `accounts.permissions.user_can_access_document()` — the same helper the detail view
> uses.

| Reader | Sees |
|---|---|
| Has access to the document | Title, area, year, and a working **View** link |
| Does not have access | *"A document you don't have access to"* — no title, no link |

This is the difference between a person choosing to mention something and the software
handing it over. The first is unavoidable; the second is a defect, and this prevents it.

It also has a pleasant side effect: attaching a document to a message becomes the
natural way for a QA Head to say *"this one — re-upload it under Area III"*, with the
link resolving correctly for the person who can act on it.

---

## 5. Interface — reuse what already exists

The QA Assistant page built on 2026-09-08 is already a two-pane messaging layout:
thread list with search and previews on the left, conversation with bubbles and a
composer on the right, all on the system's design tokens and verified at **0 contrast
failures across 113 nodes** and **0px overflow at both 1280px and 375px**.

**Messages should reuse that layout and its CSS**, not introduce a second chat style.
Concretely:

| Element | Reuse |
|---|---|
| Thread list, search, previews, timestamps | `.qa-threads`, `.qa-thread*` |
| Bubbles, avatars, message meta | `.qa-row`, `.qa-bubble`, `.qa-mini-avatar` |
| Composer and send button | `.qa-composer`, `.qa-input`, `.qa-send` |
| Attached-document card | `.qa-card` — already renders a document with chips and actions |

The work is a new page and view, not a new design. The main additions are a recipient
picker and an unread badge.

Sidebar entry: **Messages**, under Main next to QA Assistant, for every role.

---

## 6. Delivery and unread

There are no WebSockets in this stack — Django with the development server, no channel
layer. Two honest options:

1. **Notification-driven (preferred).** A new message raises a `Notification`, and the
   navbar bell already polls. The recipient sees the badge and opens Messages.
2. **Poll the open thread** every ~20 seconds while it is on screen, requesting only
   messages after the last id seen.

`Notification.CATEGORY_CHOICES` needs one addition — `message` — alongside the existing
`evidence`, `duplicate`, `completion`, `upload` and `system`.

**Do not call this real-time at the defense.** It is near-real-time by polling, which
is an appropriate choice at this scale and defensible as such. Overstating it is not.

---

## 7. Audit and retention

An `ActivityLog` row per action, following the existing naming (`edit_document`,
`delete_user`, …):

* `send_message`
* `delete_message`

Retention is the decision to settle before writing code: **are direct messages part of
the accreditation record, or private correspondence?** Both answers are defensible, and
the answer changes the build:

* *Part of the record* → administrators can read any thread; messages are included in
  exports; nothing is ever hard-deleted.
* *Private correspondence* → nobody reads another person's thread, including
  administrators, and that guarantee is stated in the interface.

Choose one and make it visible to users. The failure mode is shipping without deciding,
so people assume privacy that the software does not actually provide.

---

## 8. Tests that define "done"

1. A message attaching a document the reader cannot access renders the placeholder,
   never the title. *(§4 — the security-relevant one.)*
2. A user cannot read a thread they are not a participant in — 404, not 403.
3. A user cannot post into such a thread by crafting the request directly.
4. Unread count is correct after send, after read, and for the sender (always zero).
5. Soft-deleted messages disappear from the thread but the row survives.
6. Starting a thread with a deactivated account is rejected.
7. Every existing page still renders for all three roles with the sidebar entry added.

---

## 9. Effort

| Piece | Rough effort |
|---|---:|
| Models, migration, unread bookkeeping | 3–4 h |
| Views: inbox, thread, send, start, mark-read | 3–4 h |
| Page reusing the assistant's layout, plus recipient picker | 3–4 h |
| Permission-checked attachments (§4) | 1–2 h |
| Notifications, sidebar entry, audit | 1–2 h |
| Tests (§8) and full-suite verification | 2–3 h |
| **Total** | **~2 focused days** |

---

## 10. Optional follow-on: document discussion

Once direct messaging exists, comment threads attached to a document are a small
addition and worth having: they keep review discussion with the evidence rather than in
someone's inbox. Visibility is one rule — *whoever can open the document can read its
thread* — reusing `user_can_access_document()` with no new permission model.

Roughly a further day. Not required for the messaging feature to be useful.

---

## 11. What this plan deliberately avoids

* No WebSocket server, Redis or Channels — no new runtime dependency.
* No second chat design; the assistant's layout and tokens are reused.
* No read receipts or presence indicators. They imply real-time delivery the stack
  does not provide.
* No attempt to police message text. The system controls document access, not speech.

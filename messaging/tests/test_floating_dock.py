"""
The floating button is Messages, not the chatbot.

The button in the bottom-right corner of every page used to open the QA
Assistant and nothing else. It now opens Messages: the conversation list, one
conversation, and the assistant as the first entry in that list. What these
tests hold in place is the part that is easy to break silently -- that the dock
is rendered for every role, that it is suppressed on the two pages it would sit
on top of, that it still offers the assistant, and above all that it calls the
same messaging endpoints the Messages page calls rather than introducing routes
of its own.

The last point is the one that matters for access: a panel that reuses
``messaging:thread_detail`` inherits its rule -- you may read a thread only if
you are one of its participants -- and cannot widen it.
"""
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import Resolver404, resolve, reverse

from messaging.models import Thread, ThreadMessage


def make_user(username, role):
    user = User.objects.create_user(username, f'{username}@example.com', 'Str0ng-Passw0rd!')
    user.profile.role = role
    user.profile.save()
    return user


class DockRenderingTests(TestCase):
    """Every role gets the dock, on an ordinary page."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('dock_admin', 'admin')
        cls.head = make_user('dock_head', 'qa_staff')
        cls.faculty = make_user('dock_faculty', 'faculty')

    def page(self, user, url_name='documents:repository'):
        self.client.force_login(user)
        return self.client.get(reverse(url_name)).content.decode()

    def test_the_button_is_rendered_for_every_role(self):
        for user in (self.admin, self.head, self.faculty):
            with self.subTest(user=user.username):
                html = self.page(user)
                self.assertIn('id="qaDockFab"', html)
                self.assertIn('id="qaDockPanel"', html)

    def test_the_button_says_messages(self):
        html = self.page(self.head)
        button = html[html.index('id="qaDockFab"') - 120:html.index('id="qaDockPanel"')]
        self.assertIn('title="Messages"', button)
        self.assertIn('bi-chat-dots', button)
        self.assertNotIn('bi-robot', button.split('id="qaDockFabIcon"')[0])

    def test_the_button_carries_the_live_unread_badge(self):
        self.assertIn('data-live-badge="messages"', self.page(self.head))

    def test_the_old_chatbot_widget_is_gone(self):
        html = self.page(self.head)
        for gone in ('chatbotFab', 'chatbotWindow', 'floatingChatInput', 'chatbot-window'):
            self.assertNotIn(gone, html)

    def test_the_old_partial_no_longer_exists(self):
        """It was replaced, not left behind to be included by mistake."""
        self.assertFalse(
            (settings.BASE_DIR / 'templates' / 'chatbot' / 'floating_chatbot.html').exists())

    def test_the_dock_links_to_the_messages_page(self):
        self.assertIn('href="%s"' % reverse('messaging:inbox'), self.page(self.head))

    def test_the_assistant_is_the_first_conversation(self):
        html = self.page(self.faculty)
        self.assertIn('data-assistant="1"', html)
        self.assertIn('QA Assistant', html)
        self.assertIn('I am the QA Archive assistant', html)


class DockSuppressionTests(TestCase):
    """
    Not on the Messages page, and not on the QA Assistant page.

    The dock is fixed bottom-right, which is exactly where both of those pages
    put their own Send button. The floating widget used to swallow that click on
    the Assistant page; the same would now happen on Messages.
    """

    @classmethod
    def setUpTestData(cls):
        cls.head = make_user('dock_quiet', 'qa_staff')

    def setUp(self):
        self.client.force_login(self.head)

    def test_not_rendered_on_the_messages_page(self):
        html = self.client.get(reverse('messaging:inbox')).content.decode()
        self.assertNotIn('id="qaDockFab"', html)

    def test_not_rendered_on_the_assistant_page(self):
        html = self.client.get(reverse('chatbot:page')).content.decode()
        self.assertNotIn('id="qaDockFab"', html)

    def test_still_rendered_on_an_ordinary_page(self):
        html = self.client.get(reverse('documents:repository')).content.decode()
        self.assertIn('id="qaDockFab"', html)


class DockUnreadBadgeTests(TestCase):
    """The count on the button is the same number the sidebar shows."""

    @classmethod
    def setUpTestData(cls):
        cls.head = make_user('dock_reader', 'qa_staff')
        cls.other = make_user('dock_writer', 'faculty')

    def repository(self):
        self.client.force_login(self.head)
        return self.client.get(reverse('documents:repository')).content.decode()

    def test_no_badge_when_nothing_is_unread(self):
        html = self.repository()
        fab = html[html.index('id="qaDockFab"'):html.index('id="qaDockPanel"')]
        self.assertNotIn('sidebar-badge', fab)

    def test_the_badge_counts_unread_messages(self):
        thread, _ = Thread.get_or_create_between(self.head, self.other)
        ThreadMessage.objects.create(thread=thread, sender=self.other, body='Ready for review?')
        html = self.repository()
        fab = html[html.index('id="qaDockFab"'):html.index('id="qaDockPanel"')]
        self.assertIn('sidebar-badge', fab)
        self.assertIn('>1<', fab)


class DockEndpointTests(TestCase):
    """
    The dock adds no routes of its own.

    Every URL its script calls is pulled out of the rendered page and resolved
    against the project's URL configuration, so a hand-written path that does
    not exist -- or a new endpoint added to serve the panel instead of reusing
    the ones the Messages page uses -- fails here.
    """

    @classmethod
    def setUpTestData(cls):
        cls.head = make_user('dock_urls', 'qa_staff')

    def script(self):
        self.client.force_login(self.head)
        html = self.client.get(reverse('documents:repository')).content.decode()
        return html[html.index('id="qaDockPanel"'):]

    def test_every_url_it_calls_is_an_existing_view(self):
        urls = set(re.findall(r"'(/[a-z0-9/_-]*/)'", self.script()))
        # The two templates carry a 0 where a thread id goes.
        checked = {u.replace('/0/', '/1/') for u in urls}
        self.assertTrue(checked, 'no URLs found in the dock script')
        for url in sorted(checked):
            with self.subTest(url=url):
                try:
                    resolve(url)
                except Resolver404:  # pragma: no cover - the assertion reports it
                    self.fail('%s is not a route in this system' % url)

    def test_it_uses_the_messaging_endpoints(self):
        script = self.script()
        for expected in (reverse('messaging:sync'), reverse('messaging:thread_list'),
                         reverse('messaging:people'), reverse('messaging:thread_start'),
                         reverse('messaging:thread_detail', args=[0]),
                         reverse('messaging:message_send', args=[0])):
            self.assertIn("'%s'" % expected, script)

    def test_the_assistant_answer_comes_from_the_chatbot_api(self):
        self.assertIn("'%s'" % reverse('chatbot:api'), self.script())


class DockAccessTests(TestCase):
    """
    Reusing the endpoints means reusing their access rule.

    Stated here rather than assumed: the panel can open a thread only through
    ``messaging:thread_detail``, and that view answers a non-participant with a
    404 -- so there is no version of this panel that shows someone a
    conversation they are not in.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = make_user('dock_a', 'qa_staff')
        cls.b = make_user('dock_b', 'faculty')
        cls.outsider = make_user('dock_outsider', 'faculty')
        cls.thread, _ = Thread.get_or_create_between(cls.a, cls.b)
        ThreadMessage.objects.create(thread=cls.thread, sender=cls.a, body='Between us.')

    def test_a_participant_can_read_the_thread(self):
        self.client.force_login(self.b)
        response = self.client.get(reverse('messaging:thread_detail', args=[self.thread.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Between us.', response.content.decode())

    def test_everyone_else_gets_a_404(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('messaging:thread_detail', args=[self.thread.pk]))
        self.assertEqual(response.status_code, 404)

    def test_sending_into_someone_else_s_thread_is_refused(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse('messaging:message_send', args=[self.thread.pk]),
            data='{"body": "hello"}', content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.thread.messages.count(), 1)


class LiveBadgeTests(SimpleTestCase):
    """The unread count is now shown twice, so the poller has to update both."""

    def test_the_poller_updates_every_badge_host(self):
        js = (settings.BASE_DIR / 'static' / 'js' / 'realtime.js').read_text(encoding='utf-8')
        self.assertIn("querySelectorAll('[data-live-badge=\"'", js)
        self.assertNotIn("querySelector('[data-live-badge=\"' + kind", js)

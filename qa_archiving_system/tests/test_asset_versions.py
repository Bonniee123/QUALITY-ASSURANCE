"""
{% static_v %} follows a file that changes while the server is running.

Files replaced under a running server -- copied in from an updated checkout --
used to keep their old ?v= stamp until a restart, so the browser went on using
its cached copy and the update looked as if it had not been applied.
"""
import os

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

from qa_archiving_system.templatetags.asset_tags import static_v


class StaticVersionTests(SimpleTestCase):

    def test_a_file_changed_while_running_gets_a_new_address(self):
        path = finders.find('css/chat.css')
        before = os.stat(path)
        try:
            first = static_v('css/chat.css')
            os.utime(path, (before.st_atime, before.st_mtime + 120))
            second = static_v('css/chat.css')
            self.assertNotEqual(first, second)
            self.assertTrue(second.endswith(f'?v={int(before.st_mtime + 120)}'))
        finally:
            os.utime(path, (before.st_atime, before.st_mtime))

    def test_an_unknown_file_still_gets_its_plain_address(self):
        self.assertTrue(static_v('css/does-not-exist.css').endswith('css/does-not-exist.css'))

"""
Data written into a page's <script> cannot close that script.

The AI Processing and Dashboard charts wrote their data straight into inline
JavaScript with |safe. A cluster label ends with the title of one of its
documents ("eg. <title>"), and titles are set by whoever uploads -- Faculty
included -- so a title such as '</script><script>...' ran as script in the
Administrator's browser. The data now travels through json_script, which
escapes '<', '>' and '&'.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from documents.models import ClusterResult, Document
from qa_mapping.models import QAProgram
from qa_structure.models import AccreditationArea

PAYLOAD = '</script><script>document.title="owned"</script>'


def admin_user():
    user = User.objects.create_user('esc_admin', 'a@e.com', 'pw-12345-x')
    user.profile.role = 'admin'
    user.profile.save()
    return user


class ScriptDataEscapingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = admin_user()
        area, _ = AccreditationArea.objects.get_or_create(
            area_code='Area II', defaults={'area_name': 'Faculty'})
        cls.program = QAProgram.objects.create(name='Program ' + PAYLOAD, code='<b>P1</b>')
        doc = Document.objects.create(
            title='Plan ' + PAYLOAD, file='uploaded_documents/x.pdf', file_type='pdf',
            year=2026, document_type='Plan', acc_area=area, qa_area='Area II',
            cluster_label=0, program=cls.program, uploaded_by=cls.admin)
        ClusterResult.objects.create(document=doc, cluster_number=0,
                                     cluster_label='Area II · Plan · eg. ' + doc.title[:40])

    def setUp(self):
        self.client.force_login(self.admin)

    def assertNoScriptBreakout(self, url):
        html = self.client.get(url).content.decode()
        self.assertNotIn('</script><script>document.title', html)
        return html

    def test_a_cluster_label_cannot_run_as_script_on_ai_processing(self):
        html = self.assertNoScriptBreakout(reverse('ai_processing:list'))
        self.assertIn('\\u003C/script\\u003E', html, 'the label is still sent, escaped')

    def test_a_program_code_cannot_run_as_script_on_the_dashboard(self):
        html = self.assertNoScriptBreakout(reverse('dashboard:home'))
        self.assertNotIn('"<b>P1</b>"', html)
        self.assertIn('\\u003Cb\\u003EP1', html)

    def test_a_department_name_is_shown_as_text_on_user_management(self):
        self.admin.profile.department = '<img src=x onerror=alert(1)>'
        self.admin.profile.save()
        html = self.client.get(reverse('accounts:user_list')).content.decode()
        self.assertNotIn('<img src=x onerror', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)


class ClientEscaperTests(TestCase):
    """
    The pages' own escape helpers must escape quotes.

    They escaped by assigning textContent and reading innerHTML back, which
    leaves " and ' alone. Their output also goes into attributes: the floating
    assistant turned a URL in its answer into <a href="..."> and a document
    title such as 'https://x/"onmouseover="..."' ran as script (reproduced in a
    browser before the fix).
    """

    def test_no_page_escapes_through_innerHTML(self):
        from pathlib import Path
        from django.conf import settings
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in list((root / 'templates').rglob('*.html')) + list((root / 'static' / 'js').rglob('*.js')):
            text = path.read_text(encoding='utf-8')
            if 'textContent = s' in text and 'return d.innerHTML' in text:
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [])

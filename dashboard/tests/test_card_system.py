"""
One card surface for the whole system.

Before this, what a card looked like depended on which page it was on: four
radii (8, 10, 13 and 18px), three different border greys, shadows from none to
a 24px blur, a four-pixel lift on hover in two places, and on the dashboard a
tinted surface per metric -- five coloured slabs in the first row of the first
page anyone opens.

The rule now is one contract, declared once in style.css as --card-* tokens: a
white surface, a one-pixel neutral border, one radius, and the lightest shadow
that still separates the card from the page. Colour lives on content inside the
card -- an icon tile, a status dot, a delta badge -- never on the card itself,
which is what lets a coloured thing mean something when it appears.

These tests read the stylesheets and the templates that carry card rules, so a
page that quietly reintroduces its own card look fails here rather than in a
screenshot during a demonstration.
"""
import re

from django.conf import settings
from django.test import SimpleTestCase

CSS = settings.BASE_DIR / 'static' / 'css'
TEMPLATES = settings.BASE_DIR / 'templates'

# Every card in the system, and the file its rule lives in.
CARD_RULES = [
    ('style.css', '.card'),
    ('style.css', '.stat-card'),
    ('nexus.css', '.nx-card'),
    ('selection-cards.css', '.qa-sel-card'),
    ('selection-cards.css', '.qa-sel-detail-card'),
    ('ai-processing.css', '.ai-cluster-card'),
]

TEMPLATE_CARD_RULES = [
    ('documents/document_groups.html', '.group-card'),
    ('documents/bulk_upload.html', '.qa-batch-card'),
    ('accounts/audit_log.html', '.audit-card'),
    ('accounts/settings.html', '.settings-card'),
    ('accounts/user_list.html', '.user-management-card'),
    ('reports/reports.html', '.rpt-card'),
]


def read(kind, name):
    base = CSS if kind == 'css' else TEMPLATES
    return (base / name).read_text(encoding='utf-8')


def rule_body(source, selector):
    """The declarations of the first rule whose selector list starts with this."""
    match = re.search(r'(?m)^' + re.escape(selector) + r'\s*(?:,[^{]*)?\{([^}]*)\}', source)
    return match.group(1) if match else None


class TokenTests(SimpleTestCase):
    """The contract itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.style = read('css', 'style.css')

    def test_the_tokens_exist(self):
        for token in ('--card-bg:', '--card-border:', '--card-radius:',
                      '--card-shadow:', '--card-shadow-hover:', '--card-pad:'):
            self.assertIn(token, self.style)

    def test_the_card_surface_is_the_plain_surface_colour(self):
        self.assertIn('--card-bg: var(--color-surface);', self.style)

    def test_there_is_one_radius(self):
        self.assertIn('--card-radius: 13px;', self.style)


class SharedSurfaceTests(SimpleTestCase):
    """Every card family takes the tokens rather than its own values."""

    def assert_uses_tokens(self, source, selector, where):
        body = rule_body(source, selector)
        self.assertIsNotNone(body, '%s not found in %s' % (selector, where))
        for token in ('var(--card-border)', 'var(--card-radius)'):
            self.assertIn(token, body, '%s in %s should use %s' % (selector, where, token))

    def test_stylesheet_cards(self):
        for name, selector in CARD_RULES:
            with self.subTest(card=selector):
                self.assert_uses_tokens(read('css', name), selector, name)

    def test_cards_defined_inside_templates(self):
        for name, selector in TEMPLATE_CARD_RULES:
            with self.subTest(card=selector):
                self.assert_uses_tokens(read('tpl', name), selector, name)

    def test_the_dashboard_aliases_point_at_the_shared_tokens(self):
        """
        The dashboard keeps its --nx-* names, but they are aliases now, not a
        second palette: --nx-border-soft used to be --color-overlay, a table-row
        fill, which is why dashboard cards had a paler edge than every other card.
        """
        nexus = read('css', 'nexus.css')
        self.assertIn('--nx-radius: var(--card-radius);', nexus)
        self.assertIn('--nx-shadow: var(--card-shadow);', nexus)
        self.assertIn('--nx-border-soft: var(--card-border);', nexus)


class NoTintedCardTests(SimpleTestCase):
    """The KPI tiles are cards, not coloured panels."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.nexus = read('css', 'nexus.css')

    def test_the_old_surface_tints_are_gone(self):
        """The five tinted surfaces and their matching borders."""
        for tint in ('#eef5fa', '#fdf7e9', '#eef9f3', '#fcf0ef',
                     '#c5d6e7', '#e7dec5', '#c5e7d6', '#e7cac5'):
            self.assertNotIn(tint, self.nexus)

    def test_a_tone_colours_the_icon_and_nothing_else(self):
        for selector in ('.nx-kpi-accent-blue', '.nx-kpi-accent-amber',
                         '.nx-kpi-accent-green', '.nx-kpi-accent-danger'):
            with self.subTest(tone=selector):
                body = rule_body(self.nexus, selector)
                self.assertIsNotNone(body)
                declarations = [d.strip() for d in body.split(';') if d.strip()]
                for declaration in declarations:
                    self.assertTrue(
                        declaration.startswith('--nx-tone-'),
                        '%s sets %r; a tone may only set the icon tokens'
                        % (selector, declaration))

    def test_the_icon_tile_takes_the_tone(self):
        body = rule_body(self.nexus, '.nx-kpi .nx-kpi-label .nx-i')
        self.assertIn('var(--nx-tone-bg', body)
        self.assertIn('var(--nx-tone-accent', body)

    def test_the_label_is_ordinary_label_ink(self):
        """It was uppercase, tracked out, and in the tone's own colour."""
        body = rule_body(self.nexus, '.nx-kpi .nx-kpi-label')
        self.assertIn('text-transform: none', body)
        self.assertIn('color: var(--nx-text-mute)', body)


class QuietHoverTests(SimpleTestCase):
    """Hover answers with the edge and the shadow. Nothing moves."""

    def test_no_card_lifts_on_hover(self):
        for kind, name, selector in (
            ('css', 'style.css', '.card:hover'),
            ('css', 'style.css', '.stat-card:hover'),
            ('css', 'nexus.css', '.nx-card:hover'),
            ('css', 'selection-cards.css', '.qa-sel-card:hover'),
            ('css', 'ai-processing.css', '.ai-cluster-card:hover'),
            ('tpl', 'accounts/settings.html', '.settings-card:hover'),
        ):
            with self.subTest(card=selector):
                body = rule_body(read(kind, name), selector)
                self.assertIsNotNone(body, '%s not found' % selector)
                self.assertNotIn('translate', body)

    def test_the_selection_grid_does_not_repaint_its_surface_on_hover(self):
        """Twenty cards changing background under the pointer reads as flicker."""
        body = rule_body(read('css', 'selection-cards.css'), '.qa-sel-card:hover')
        self.assertNotIn('background', body)

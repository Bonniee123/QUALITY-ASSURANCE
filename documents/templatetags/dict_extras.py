"""Template filters for working with dicts (used by faceted search counts)."""
import re

from django import template

register = template.Library()


@register.filter(name='get_item')
def get_item(value, key):
    """Look up `key` in dict `value`. Tries the raw key first, then a string version."""
    if value is None:
        return None
    if isinstance(value, dict):
        if key in value:
            return value[key]
        try:
            return value.get(str(key))
        except Exception:
            return None
    return None


@register.filter(name='readable_ink')
def readable_ink(background):
    """
    Pick black or white text for a background colour chosen at runtime.

    QA programs carry a user-selected colour, and the badges that show a program
    code hardcoded `color: white` on top of it. A light program colour therefore
    produced unreadable text -- the amber in the seeded data measured 2.13:1
    against white, well under the 4.5:1 minimum. This returns whichever of dark
    ink or white actually contrasts with the given colour, so the badge stays
    legible whatever colour someone picks.

    Falls back to white on anything it cannot parse, which is the previous
    behaviour, so an unexpected value can never make the badge disappear.
    """
    DARK, LIGHT = '#111827', '#ffffff'
    if not background:
        return LIGHT
    raw = str(background).strip()

    channels = None
    # Programs store their colour as an hsl() string, not hex, so both are parsed.
    hsl_match = re.match(
        r'hsla?\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%', raw, re.I
    )
    if hsl_match:
        h = float(hsl_match.group(1)) % 360
        s = float(hsl_match.group(2)) / 100
        lightness = float(hsl_match.group(3)) / 100
        a = s * min(lightness, 1 - lightness)

        def component(n):
            k = (n + h / 30) % 12
            return lightness - a * max(-1, min(k - 3, min(9 - k, 1)))

        channels = [component(n) for n in (0, 8, 4)]
    else:
        value = raw.lstrip('#')
        if len(value) == 3:
            value = ''.join(ch * 2 for ch in value)
        if len(value) == 6:
            try:
                channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            except ValueError:
                channels = None
    if channels is None:
        return LIGHT

    def linear(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Contrast against white vs against near-black; take whichever is higher.
    against_white = 1.05 / (luminance + 0.05)
    against_dark = (luminance + 0.05) / 0.05
    return LIGHT if against_white >= against_dark else DARK

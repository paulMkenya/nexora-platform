"""Readable text colour on top of a brand colour (white-label safe)."""
import re

from django import template

register = template.Library()

_HEX = re.compile(r'^#([0-9a-fA-F]{6})$')


def _luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


@register.filter
def safe_hex(value, fallback='#6366f1'):
    """The value if it is a #rrggbb colour, else the fallback (keeps CSS injection out)."""
    return value if _HEX.match(value or '') else fallback


@register.filter
def on_color(value):
    """'#ffffff' or a near-black, whichever has more contrast on ``value``."""
    if not _HEX.match(value or ''):
        return '#ffffff'
    lum = _luminance(value)
    white = 1.05 / (lum + 0.05)
    dark = (lum + 0.05) / (_luminance('#0b0e17') + 0.05)
    return '#ffffff' if white >= dark else '#0b0e17'

"""Server-rendered chart geometry — the numbers behind the inline SVG.

Nexora renders every chart as inline SVG produced by Django. There is no
charting library and no client-side JS: see RESUME_NOTES.md, which bans
vendored JS/islands until a spike is approved. So the arithmetic that a chart
library would normally do in the browser happens here instead, and the
templates under ``templates/partials/charts/`` stay dumb — they emit the
attributes this module hands them and nothing more.

Why the split: SVG path/arc math is unreadable and untestable inside a Django
template, and every attempt to express it with ``{% widthratio %}`` ends in
rounding drift. Keeping it in Python makes each chart a pure function of its
data, which is both testable (``nexora/tests/test_charts.py``) and cheap.

COLOR CONTRACT — read before adding a chart.
Nothing here picks a color literal. Every function emits a CSS ``var(...)``
reference, and the values live in ``static/css/charts.css``:

  * **Status** data (safe/review/blocked, approved/pending/rejected) uses the
    reserved semantic tokens from ``tokens.css`` — ``--pos``/``--warn``/``--neg``.
    These are never reused as a categorical series color.
  * **Categorical** data (traffic sources, buyers, offers) uses the ``--viz-N``
    slots, assigned in fixed order and *never cycled*. Slot order is
    blue, orange, teal, violet, magenta, green; both the light and dark steps
    were validated for lightness band, chroma floor, colorblind separation,
    normal-vision separation and surface contrast. Re-run that validation if
    you change a value. A 7th series is not a new hue — fold it into "Other".

Because the operator canvas (``.nx-content--light-canvas``) is light in *both*
themes while affiliate/advertiser surfaces follow the theme, the slots are
defined for both surfaces in CSS and swap there, not here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# Fixed categorical slot order. Index -> CSS custom property.
VIZ_SLOTS = 6

# Semantic tones that map straight onto the reserved status tokens. Anything
# not in here is treated as a categorical slot name.
STATUS_TONES = {
    'pos': 'var(--pos)',
    'warn': 'var(--warn)',
    'neg': 'var(--neg)',
    'blue': 'var(--brand-blue)',
    'teal': 'var(--brand-teal)',
    'muted': 'var(--text-faint)',
}


def color_for(tone: Optional[str], index: int) -> str:
    """Resolve a segment's color to a CSS var reference.

    ``tone`` wins when it names a reserved status token; otherwise the segment
    takes categorical slot ``index`` (0-based, fixed order, no cycling — a
    slot past the end falls back to the muted token rather than wrapping round
    and repeating a hue that already means something else on the same chart).
    """
    if tone:
        resolved = STATUS_TONES.get(tone)
        if resolved:
            return resolved
    if index >= VIZ_SLOTS:
        return STATUS_TONES['muted']
    return f'var(--viz-{index + 1})'


def _pct(value: float, total: float) -> float:
    return (value / total * 100.0) if total else 0.0


@dataclass(frozen=True)
class Segment:
    label: str
    value: float
    pct: float
    color: str
    dash: str
    offset: str


def donut(segments: Iterable, *, size: int = 180, thickness: int = 20, gap: float = 2.0) -> dict:
    """Ring chart drawn with ``stroke-dasharray`` on concentric circles.

    Each segment is one ``<circle>`` sharing the same geometry, distinguished
    only by its dash pattern and offset — no arc paths, so there is no
    large-arc-flag edge case at 50% and no cumulative rounding drift.

    ``segments`` accepts ``(label, value)`` or ``(label, value, tone)``. A
    2px ``gap`` is subtracted from every arc so adjacent fills are separated
    by the surface rather than touching (a segment smaller than the gap keeps
    a hairline so it never inverts into a negative dash).

    Returns a dict ready for ``partials/charts/donut.html``. ``empty`` is True
    when every value is zero, which the template renders as a single track
    ring — a donut of nothing is otherwise indistinguishable from a bug.
    """
    items = [tuple(s) for s in segments]
    total = float(sum(float(s[1]) for s in items))

    radius = (size - thickness) / 2.0
    circumference = 2 * math.pi * radius

    out: list[Segment] = []
    cumulative = 0.0
    for index, item in enumerate(items):
        label = str(item[0])
        value = float(item[1])
        tone = item[2] if len(item) > 2 else None

        share = (value / total) if total else 0.0
        arc = share * circumference
        drawn = max(arc - gap, 0.5) if arc > 0 else 0.0

        out.append(Segment(
            label=label,
            value=value,
            pct=round(_pct(value, total), 1),
            color=color_for(tone, index),
            dash=f'{drawn:.3f} {circumference - drawn:.3f}',
            offset=f'{-cumulative:.3f}',
        ))
        cumulative += arc

    return {
        'size': size,
        'thickness': thickness,
        'radius': round(radius, 3),
        'center': size / 2.0,
        'circumference': round(circumference, 3),
        'total': total,
        'segments': out,
        'empty': total <= 0,
    }


def _scaled(values: Sequence[float], height: float, pad: float) -> tuple[list[float], float, float]:
    """Map values onto y pixels (SVG y grows downward, so high value = low y)."""
    lo = min(values)
    hi = max(values)
    if hi == lo:
        # A flat series has no range to scale against — pin it mid-box so it
        # reads as "steady", not as a line stuck to the floor or the ceiling.
        mid = height / 2.0
        return [mid for _ in values], lo, hi
    span = hi - lo
    usable = height - (pad * 2)
    return [pad + (hi - v) / span * usable for v in values], lo, hi


def sparkline(values: Sequence[float], *, width: int = 130, height: int = 36, pad: float = 3.0) -> dict:
    """A single unlabelled trend line for a stat tile.

    Deliberately axis-free and tooltip-free: a sparkline's job is the shape of
    the trend beside a number that already carries the value. Returns both the
    ``points`` for the stroke and a closed ``area`` path for the fill.
    """
    values = [float(v) for v in values]
    if len(values) < 2:
        return {'width': width, 'height': height, 'points': '', 'area': '', 'empty': True}

    step = width / (len(values) - 1)
    ys, lo, hi = _scaled(values, height, pad)
    xs = [i * step for i in range(len(values))]

    points = ' '.join(f'{x:.2f},{y:.2f}' for x, y in zip(xs, ys))
    area = (f'M0,{height:.2f} L'
            + ' L'.join(f'{x:.2f},{y:.2f}' for x, y in zip(xs, ys))
            + f' L{width:.2f},{height:.2f} Z')

    return {
        'width': width,
        'height': height,
        'points': points,
        'area': area,
        'low': lo,
        'high': hi,
        'empty': False,
    }


def bar_chart(items: Iterable, *, width: int = 560, height: int = 220, gap: float = 2.0,
              pad_bottom: float = 26.0) -> dict:
    """Vertical bars for comparing magnitude across a handful of categories.

    Bars are anchored to the baseline with 4px rounded tops (``rx``), and a
    2px ``gap`` of surface separates neighbours. ``items`` accepts
    ``(label, value)`` or ``(label, value, tone)``.
    """
    items = [tuple(i) for i in items]
    if not items:
        return {'width': width, 'height': height, 'bars': [], 'empty': True, 'max': 0}

    values = [float(i[1]) for i in items]
    peak = max(values) or 1.0
    plot_h = height - pad_bottom

    slot = width / len(items)
    bar_w = max(slot - gap * 2, 1.0)

    bars = []
    for index, item in enumerate(items):
        value = float(item[1])
        tone = item[2] if len(item) > 2 else None
        bar_h = (value / peak) * plot_h if peak else 0.0
        bars.append({
            'label': str(item[0]),
            'value': value,
            'x': round(index * slot + gap, 2),
            'y': round(plot_h - bar_h, 2),
            'width': round(bar_w, 2),
            'height': round(max(bar_h, 0.0), 2),
            'label_x': round(index * slot + slot / 2.0, 2),
            'color': color_for(tone, index),
        })

    return {
        'width': width,
        'height': height,
        'plot_height': round(plot_h, 2),
        'baseline': round(plot_h, 2),
        'label_y': round(plot_h + 18, 2),
        'bars': bars,
        'max': peak,
        'empty': False,
    }


def area_chart(series: Iterable, x_labels: Sequence[str] = (), *, width: int = 720, height: int = 260,
               pad_bottom: float = 28.0, pad_top: float = 12.0, gridlines: int = 4) -> dict:
    """Multi-series trend over time, one shared y-axis.

    One axis only — two measures of different scale get two charts, never a
    second y-axis. All series are scaled against a single common range so the
    comparison between them is honest.

    ``series`` items are dicts: ``{'label': str, 'values': [...], 'tone': str}``
    (``tone`` optional; omitted means categorical slot by position).
    """
    series = [dict(s) for s in series]
    series = [s for s in series if s.get('values')]
    if not series:
        return {'width': width, 'height': height, 'series': [], 'empty': True, 'gridlines': [], 'x_labels': []}

    every = [float(v) for s in series for v in s['values']]
    hi = max(every)
    lo = min(min(every), 0.0)
    span = (hi - lo) or 1.0

    plot_h = height - pad_bottom - pad_top
    length = max(len(s['values']) for s in series)
    step = width / (length - 1) if length > 1 else width

    def y_for(value: float) -> float:
        return pad_top + (hi - value) / span * plot_h

    out = []
    for index, s in enumerate(series):
        values = [float(v) for v in s['values']]
        xs = [i * step for i in range(len(values))]
        ys = [y_for(v) for v in values]
        points = ' '.join(f'{x:.2f},{y:.2f}' for x, y in zip(xs, ys))
        baseline = pad_top + plot_h
        out.append({
            'label': s['label'],
            'color': color_for(s.get('tone'), index),
            'points': points,
            'area': (f'M0,{baseline:.2f} L'
                     + ' L'.join(f'{x:.2f},{y:.2f}' for x, y in zip(xs, ys))
                     + f' L{xs[-1]:.2f},{baseline:.2f} Z'),
            'last_x': round(xs[-1], 2),
            'last_y': round(ys[-1], 2),
            'last_value': values[-1],
        })

    grid = []
    for i in range(gridlines + 1):
        value = hi - (span * i / gridlines)
        grid.append({'y': round(y_for(value), 2), 'value': round(value, 2)})

    labels = []
    if x_labels:
        stride = max(len(x_labels) // 6, 1)
        for i, label in enumerate(x_labels):
            if i % stride == 0 or i == len(x_labels) - 1:
                labels.append({'x': round(i * step, 2), 'label': label})

    return {
        'width': width,
        'height': height,
        'plot_height': round(plot_h, 2),
        'baseline': round(pad_top + plot_h, 2),
        'label_y': round(pad_top + plot_h + 18, 2),
        'series': out,
        'gridlines': grid,
        'x_labels': labels,
        'max': hi,
        'min': lo,
        'empty': False,
    }


def meter(value: float, total: float, *, tone: Optional[str] = None) -> dict:
    """A single progress bar (payout thresholds, cap utilisation, offer share).

    Not SVG — the template renders this as two nested divs — but the clamping
    and percentage rounding belong with the rest of the chart arithmetic
    rather than being re-derived with ``{% widthratio %}`` at each call site.
    """
    pct = _pct(float(value), float(total))
    clamped = max(0.0, min(pct, 100.0))
    return {
        'value': value,
        'total': total,
        'pct': round(pct, 1),
        'width_pct': round(clamped, 2),
        'color': color_for(tone, 0) if tone else 'var(--brand-blue)',
        'over': pct > 100.0,
    }

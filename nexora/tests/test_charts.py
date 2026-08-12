"""Chart geometry — pure arithmetic, no Django needed.

These pin the properties that are invisible in a rendered page until they are
wrong: that a ring's arcs actually sum to the circle, that a flat series does
not collapse onto an axis, that no chart divides by zero on empty data, and
that the categorical slots are assigned in fixed order and never cycled.
"""
import math

import pytest

from nexora import charts


class TestColorFor:
    def test_status_tone_wins_over_slot(self):
        assert charts.color_for('pos', 3) == 'var(--pos)'
        assert charts.color_for('neg', 0) == 'var(--neg)'

    def test_categorical_slots_assigned_by_position(self):
        assert charts.color_for(None, 0) == 'var(--viz-1)'
        assert charts.color_for(None, 2) == 'var(--viz-3)'

    def test_slots_do_not_cycle_past_the_end(self):
        # Wrapping round would repeat a hue that already means another series
        # on the same chart. Past the end we go muted instead.
        assert charts.color_for(None, charts.VIZ_SLOTS) == charts.STATUS_TONES['muted']
        assert charts.color_for(None, charts.VIZ_SLOTS + 5) == charts.STATUS_TONES['muted']

    def test_unknown_tone_falls_through_to_slot(self):
        assert charts.color_for('not-a-token', 1) == 'var(--viz-2)'


class TestDonut:
    def test_shares_and_offsets_cover_the_circle(self):
        chart = charts.donut([('Safe', 72, 'pos'), ('Review', 18, 'warn'), ('Blocked', 10, 'neg')])

        assert [s.pct for s in chart['segments']] == [72.0, 18.0, 10.0]
        assert [s.color for s in chart['segments']] == ['var(--pos)', 'var(--warn)', 'var(--neg)']

        # Each segment starts where the previous one ended: the offsets are the
        # running total, negated. The last one lands a full circle round.
        offsets = [-float(s.offset) for s in chart['segments']]
        assert offsets[0] == pytest.approx(0.0)
        circumference = chart['circumference']
        assert offsets[1] == pytest.approx(circumference * 0.72, abs=0.01)
        assert offsets[2] == pytest.approx(circumference * 0.90, abs=0.01)

    def test_arc_lengths_sum_to_the_circumference(self):
        chart = charts.donut([('a', 1), ('b', 1), ('c', 1), ('d', 1)], gap=0.0)
        drawn = sum(float(s.dash.split()[0]) for s in chart['segments'])
        assert drawn == pytest.approx(chart['circumference'], abs=0.01)

    def test_gap_separates_neighbours_without_going_negative(self):
        # A hair-thin segment must not produce a negative dash (which SVG
        # renders as a full ring — the segment would swallow the chart).
        chart = charts.donut([('tiny', 0.01), ('rest', 999)], gap=2.0)
        for seg in chart['segments']:
            assert float(seg.dash.split()[0]) > 0

    def test_empty_data_is_flagged_not_divided_by_zero(self):
        chart = charts.donut([('a', 0), ('b', 0)])
        assert chart['empty'] is True
        assert all(s.pct == 0.0 for s in chart['segments'])

    def test_no_segments_at_all(self):
        chart = charts.donut([])
        assert chart['empty'] is True
        assert chart['segments'] == []

    def test_geometry_keeps_the_stroke_inside_the_viewbox(self):
        chart = charts.donut([('a', 1)], size=180, thickness=20)
        # radius + half the stroke must not exceed the half-size, or the ring
        # is clipped by the viewBox edge.
        assert chart['radius'] + chart['thickness'] / 2 == pytest.approx(chart['size'] / 2)
        assert chart['circumference'] == pytest.approx(2 * math.pi * chart['radius'], abs=0.01)


class TestSparkline:
    def test_produces_a_point_per_value(self):
        chart = charts.sparkline([1, 5, 3, 9])
        assert len(chart['points'].split(' ')) == 4
        assert chart['empty'] is False

    def test_high_values_sit_above_low_ones(self):
        chart = charts.sparkline([0, 10])
        first, last = chart['points'].split(' ')
        first_y = float(first.split(',')[1])
        last_y = float(last.split(',')[1])
        # SVG y grows downward, so the larger value must have the smaller y.
        assert last_y < first_y

    def test_flat_series_sits_mid_box(self):
        # A flat line pinned to the floor reads as "zero", which is a lie when
        # the series is a steady 500.
        chart = charts.sparkline([500, 500, 500], height=36)
        ys = {float(p.split(',')[1]) for p in chart['points'].split(' ')}
        assert ys == {18.0}

    def test_too_short_to_plot_is_flagged(self):
        assert charts.sparkline([])['empty'] is True
        assert charts.sparkline([7])['empty'] is True

    def test_area_path_is_closed(self):
        chart = charts.sparkline([1, 2, 3])
        assert chart['area'].startswith('M0,')
        assert chart['area'].endswith('Z')


class TestBarChart:
    def test_tallest_bar_fills_the_plot_height(self):
        chart = charts.bar_chart([('a', 5), ('b', 10)])
        tallest = max(chart['bars'], key=lambda b: b['height'])
        assert tallest['height'] == pytest.approx(chart['plot_height'])
        assert tallest['label'] == 'b'

    def test_bars_are_anchored_to_the_baseline(self):
        chart = charts.bar_chart([('a', 3), ('b', 7), ('c', 1)])
        for bar in chart['bars']:
            assert bar['y'] + bar['height'] == pytest.approx(chart['baseline'], abs=0.01)

    def test_bars_do_not_overlap(self):
        chart = charts.bar_chart([('a', 1), ('b', 2), ('c', 3)])
        for left, right in zip(chart['bars'], chart['bars'][1:]):
            assert left['x'] + left['width'] <= right['x'] + 0.001

    def test_all_zero_values_do_not_divide_by_zero(self):
        chart = charts.bar_chart([('a', 0), ('b', 0)])
        assert chart['empty'] is False
        assert all(b['height'] == 0 for b in chart['bars'])

    def test_no_items(self):
        assert charts.bar_chart([])['empty'] is True

    def test_slots_assigned_in_order(self):
        chart = charts.bar_chart([('a', 1), ('b', 1), ('c', 1)])
        assert [b['color'] for b in chart['bars']] == ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)']


class TestAreaChart:
    def test_series_share_one_scale(self):
        # The whole point of a single axis: the taller series must plot higher
        # than the shorter one at the same index.
        chart = charts.area_chart([
            {'label': 'Leads', 'values': [10, 20, 30]},
            {'label': 'Conversions', 'values': [1, 2, 3]},
        ])
        leads, conversions = chart['series']
        leads_y = [float(p.split(',')[1]) for p in leads['points'].split(' ')]
        conv_y = [float(p.split(',')[1]) for p in conversions['points'].split(' ')]
        assert all(a < b for a, b in zip(leads_y, conv_y))

    def test_peak_touches_the_top_of_the_plot(self):
        chart = charts.area_chart([{'label': 'A', 'values': [0, 100]}], pad_top=12.0)
        ys = [float(p.split(',')[1]) for p in chart['series'][0]['points'].split(' ')]
        assert min(ys) == pytest.approx(12.0)

    def test_gridlines_span_the_range(self):
        chart = charts.area_chart([{'label': 'A', 'values': [0, 50]}], gridlines=4)
        assert len(chart['gridlines']) == 5
        assert chart['gridlines'][0]['value'] == pytest.approx(50)
        assert chart['gridlines'][-1]['value'] == pytest.approx(0)

    def test_x_labels_are_thinned_not_crowded(self):
        labels = [f'D{i}' for i in range(30)]
        chart = charts.area_chart([{'label': 'A', 'values': list(range(30))}], labels)
        assert len(chart['x_labels']) <= 8
        assert chart['x_labels'][-1]['label'] == 'D29'

    def test_last_value_is_exposed_for_direct_labelling(self):
        chart = charts.area_chart([{'label': 'A', 'values': [4, 9]}])
        assert chart['series'][0]['last_value'] == 9

    def test_empty_and_all_empty_series(self):
        assert charts.area_chart([])['empty'] is True
        assert charts.area_chart([{'label': 'A', 'values': []}])['empty'] is True

    def test_area_paths_are_closed(self):
        chart = charts.area_chart([{'label': 'A', 'values': [1, 2, 3]}])
        assert chart['series'][0]['area'].endswith('Z')


class TestMeter:
    def test_basic_share(self):
        m = charts.meter(25, 100)
        assert m['pct'] == 25.0
        assert m['width_pct'] == 25.0
        assert m['over'] is False

    def test_overflow_is_flagged_but_the_bar_is_clamped(self):
        m = charts.meter(150, 100)
        assert m['pct'] == 150.0
        assert m['width_pct'] == 100.0
        assert m['over'] is True

    def test_zero_total_does_not_divide_by_zero(self):
        m = charts.meter(0, 0)
        assert m['pct'] == 0.0
        assert m['width_pct'] == 0.0

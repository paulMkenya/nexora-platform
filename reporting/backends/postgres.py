from __future__ import annotations

import base64
import json
from datetime import datetime
from decimal import Decimal

from django.db.models import Sum

from .base import AggregationBackend, ReportPage

# Maps API group_by name → model field name in the matviews
_GROUP_FIELD_MAP = {
    'period': 'period',
    'offer': 'offer_id',
    'affiliate': 'affiliate_id',
    'country': 'country',
    'traffic_source': 'traffic_source',
    'device': 'device_type',
    'brand': 'brand_id',
}

_DEFAULT_GROUP_BY = ['period']


def _encode_cursor(offset: int) -> str:
    return base64.b64encode(json.dumps({'o': offset}).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        return int(json.loads(base64.b64decode(cursor.encode()).decode())['o'])
    except Exception:
        return 0


class PostgresMatViewBackend(AggregationBackend):
    """
    Postgres materialized view backend.

    Chooses hourly granularity for ranges ≤ 3 days; daily otherwise.
    Re-aggregates on the fly when the user requests coarser group_by dimensions.
    """

    def _choose_click_model(self, date_from: datetime, date_to: datetime):
        from reporting.models import ClickDailyStats, ClickHourlyStats
        delta = (date_to.date() - date_from.date()).days if hasattr(date_to, 'date') else (date_to - date_from).days
        return ClickHourlyStats if delta <= 3 else ClickDailyStats

    def _choose_conv_model(self, date_from: datetime, date_to: datetime):
        from reporting.models import ConversionDailyStats, ConversionHourlyStats
        delta = (date_to.date() - date_from.date()).days if hasattr(date_to, 'date') else (date_to - date_from).days
        return ConversionHourlyStats if delta <= 3 else ConversionDailyStats

    def _apply_filters(self, qs, filters: dict):
        if filters.get('offer_id'):
            qs = qs.filter(offer_id=filters['offer_id'])
        if filters.get('country'):
            qs = qs.filter(country__iexact=filters['country'])
        if filters.get('device'):
            qs = qs.filter(device_type=filters['device'])
        if filters.get('traffic_source'):
            qs = qs.filter(traffic_source=filters['traffic_source'])
        if filters.get('affiliate_id'):
            qs = qs.filter(affiliate_id=filters['affiliate_id'])
        return qs

    def _paginate(self, qs, cursor, page_size):
        offset = _decode_cursor(cursor) if cursor else 0
        rows = list(qs[offset: offset + page_size + 1])
        has_next = len(rows) > page_size
        return rows[:page_size], _encode_cursor(offset + page_size) if has_next else None

    def clicks_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size) -> ReportPage:
        Model = self._choose_click_model(date_from, date_to)
        qs = Model.objects.filter(brand_id=brand_id, period__gte=date_from, period__lte=date_to)
        qs = self._apply_filters(qs, filters)

        group_fields = [_GROUP_FIELD_MAP[g] for g in (group_by or _DEFAULT_GROUP_BY) if g in _GROUP_FIELD_MAP]
        qs = (
            qs.values(*group_fields)
            .annotate(clicks=Sum('clicks'), revenue=Sum('revenue'), payout=Sum('payout'))
            .order_by(*[f'-{f}' if f == 'period' else f for f in group_fields])
        )

        rows, next_cursor = self._paginate(qs, cursor, page_size)
        return ReportPage(results=list(rows), next_cursor=next_cursor)

    def conversions_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size) -> ReportPage:
        Model = self._choose_conv_model(date_from, date_to)
        qs = Model.objects.filter(brand_id=brand_id, period__gte=date_from, period__lte=date_to)
        qs = self._apply_filters(qs, filters)

        group_fields = [_GROUP_FIELD_MAP[g] for g in (group_by or _DEFAULT_GROUP_BY) if g in _GROUP_FIELD_MAP]
        qs = (
            qs.values(*group_fields)
            .annotate(
                conversions_total=Sum('conversions_total'),
                conversions_approved=Sum('conversions_approved'),
                conversions_rejected=Sum('conversions_rejected'),
                conversions_hold=Sum('conversions_hold'),
                revenue=Sum('revenue'),
                payout=Sum('payout'),
            )
            .order_by(*[f'-{f}' if f == 'period' else f for f in group_fields])
        )

        rows, next_cursor = self._paginate(qs, cursor, page_size)
        return ReportPage(results=list(rows), next_cursor=next_cursor)

    def revenue_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size) -> ReportPage:
        """
        Joins click and conversion daily stats, computing EPC and CR.
        Uses raw SQL to join both matviews in a single query.
        """
        from django.db import connection

        delta = (date_to.date() - date_from.date()).days if hasattr(date_to, 'date') else (date_to - date_from).days
        click_table = 'reporting_click_hourly' if delta <= 3 else 'reporting_click_daily'
        conv_table = 'reporting_conversion_hourly' if delta <= 3 else 'reporting_conversion_daily'

        group_fields = [_GROUP_FIELD_MAP[g] for g in (group_by or _DEFAULT_GROUP_BY) if g in _GROUP_FIELD_MAP]

        # Build WHERE clause args
        where_args: list = [brand_id, date_from, date_to, brand_id, date_from, date_to]
        extra_click = ''
        extra_conv = ''
        if filters.get('offer_id'):
            extra_click += ' AND c.offer_id = %s'
            extra_conv += ' AND v.offer_id = %s'
            where_args.insert(3, filters['offer_id'])
            where_args.append(filters['offer_id'])
        if filters.get('country'):
            extra_click += ' AND LOWER(c.country) = LOWER(%s)'
            extra_conv += ' AND LOWER(v.country) = LOWER(%s)'
            where_args.insert(3 + (1 if filters.get('offer_id') else 0), filters['country'])
            where_args.append(filters['country'])

        # Build SELECT and GROUP BY lists
        click_aliases = {
            'period': 'c.period', 'offer_id': 'c.offer_id', 'affiliate_id': 'c.affiliate_id',
            'country': 'c.country', 'traffic_source': 'c.traffic_source', 'device_type': 'c.device_type',
            'brand_id': 'c.brand_id',
        }
        conv_aliases = {
            'period': 'v.period', 'offer_id': 'v.offer_id', 'affiliate_id': 'v.affiliate_id',
            'country': 'v.country', 'traffic_source': 'v.traffic_source', 'device_type': 'v.device_type',
            'brand_id': 'v.brand_id',
        }

        select_parts = [f'COALESCE({click_aliases[f]}, {conv_aliases[f]}) AS {f}' for f in group_fields]
        group_by_sql = ', '.join([f'COALESCE({click_aliases[f]}, {conv_aliases[f]})' for f in group_fields])
        order_by_sql = 'COALESCE(c.period, v.period) DESC' if 'period' in group_fields else '1'

        select_sql = ', '.join(select_parts) + ', ' if select_parts else ''

        sql = f"""
            SELECT
                {select_sql}
                COALESCE(SUM(c.clicks), 0)                                             AS clicks,
                COALESCE(SUM(v.conversions_approved), 0)                               AS conversions,
                COALESCE(SUM(c.revenue), 0) + COALESCE(SUM(v.revenue), 0)             AS total_revenue,
                COALESCE(SUM(c.payout), 0)  + COALESCE(SUM(v.payout), 0)              AS total_payout,
                CASE WHEN COALESCE(SUM(c.clicks), 0) > 0
                     THEN ROUND((COALESCE(SUM(c.revenue), 0) + COALESCE(SUM(v.revenue), 0))
                                / NULLIF(SUM(c.clicks), 0), 4)
                     ELSE 0 END                                                        AS epc,
                CASE WHEN COALESCE(SUM(c.clicks), 0) > 0
                     THEN ROUND(COALESCE(SUM(v.conversions_approved), 0)::numeric
                                / NULLIF(SUM(c.clicks), 0) * 100, 2)
                     ELSE 0 END                                                        AS cr_pct
            FROM {click_table} c
            FULL OUTER JOIN {conv_table} v
              ON c.period = v.period AND c.brand_id = v.brand_id
             AND c.offer_id IS NOT DISTINCT FROM v.offer_id
             AND c.affiliate_id IS NOT DISTINCT FROM v.affiliate_id
             AND c.country = v.country
             AND c.traffic_source = v.traffic_source
             AND c.device_type = v.device_type
            WHERE (c.brand_id = %s OR v.brand_id = %s)
              AND (c.period >= %s OR v.period >= %s)
              AND (c.period <= %s OR v.period <= %s)
            {f'GROUP BY {group_by_sql}' if group_by_sql else ''}
            ORDER BY {order_by_sql}
        """

        revenue_args = [brand_id, brand_id, date_from, date_from, date_to, date_to]

        offset = _decode_cursor(cursor) if cursor else 0
        with connection.cursor() as cur:
            cur.execute(sql, revenue_args)
            cols = [d[0] for d in cur.description]
            all_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        page = all_rows[offset: offset + page_size]
        has_next = len(all_rows) > offset + page_size
        next_cursor = _encode_cursor(offset + page_size) if has_next else None

        # Ensure Decimal serialisability
        for row in page:
            for k, v in row.items():
                if isinstance(v, Decimal):
                    row[k] = float(v)

        return ReportPage(results=page, next_cursor=next_cursor)

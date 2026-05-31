"""
Creates four Postgres materialized views for reporting aggregation.

Views:
  reporting_click_hourly   – click metrics bucketed to the hour
  reporting_click_daily    – click metrics bucketed to the day
  reporting_conversion_hourly  – conversion metrics bucketed to the hour
  reporting_conversion_daily   – conversion metrics bucketed to the day

Each view includes a ROW_NUMBER()-based 'id' column so Django's ORM can treat
the view as a queryable model.  Unique indexes on 'id' enable CONCURRENTLY
refreshes in production.

Device type is derived from the ua string with a regex CASE expression.
Traffic source is taken from sub1 (standard industry convention).
"""
from django.db import migrations

_DEVICE_CASE = """
CASE
    WHEN ua ~* '(mobile|android|iphone|ipod|blackberry|windows phone|opera mini|opera mobi)'
        THEN 'mobile'
    WHEN ua ~* '(tablet|ipad)'
        THEN 'tablet'
    ELSE 'desktop'
END
"""

_CREATE_CLICK_HOURLY = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS reporting_click_hourly AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY period DESC, brand_id, offer_id NULLS LAST, affiliate_id NULLS LAST, country, traffic_source
    ) AS id,
    period,
    brand_id,
    offer_id,
    affiliate_id,
    country,
    traffic_source,
    device_type,
    SUM(clicks)         AS clicks,
    SUM(revenue)        AS revenue,
    SUM(payout)         AS payout,
    AVG(avg_fraud_score) AS avg_fraud_score
FROM (
    SELECT
        date_trunc('hour', created_at)  AS period,
        brand_id,
        offer_id,
        affiliate_id,
        country,
        sub1                            AS traffic_source,
        {_DEVICE_CASE}                  AS device_type,
        COUNT(*)                        AS clicks,
        SUM(revenue)                    AS revenue,
        SUM(payout)                     AS payout,
        AVG(fraud_score::float)         AS avg_fraud_score
    FROM tracker_click
    GROUP BY 1, 2, 3, 4, 5, 6, 7
) _agg
GROUP BY period, brand_id, offer_id, affiliate_id, country, traffic_source, device_type
WITH DATA;
"""

_CREATE_CLICK_DAILY = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS reporting_click_daily AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY period DESC, brand_id, offer_id NULLS LAST, affiliate_id NULLS LAST, country, traffic_source
    ) AS id,
    period,
    brand_id,
    offer_id,
    affiliate_id,
    country,
    traffic_source,
    device_type,
    SUM(clicks)         AS clicks,
    SUM(revenue)        AS revenue,
    SUM(payout)         AS payout,
    AVG(avg_fraud_score) AS avg_fraud_score
FROM (
    SELECT
        date_trunc('day', created_at)   AS period,
        brand_id,
        offer_id,
        affiliate_id,
        country,
        sub1                            AS traffic_source,
        {_DEVICE_CASE}                  AS device_type,
        COUNT(*)                        AS clicks,
        SUM(revenue)                    AS revenue,
        SUM(payout)                     AS payout,
        AVG(fraud_score::float)         AS avg_fraud_score
    FROM tracker_click
    GROUP BY 1, 2, 3, 4, 5, 6, 7
) _agg
GROUP BY period, brand_id, offer_id, affiliate_id, country, traffic_source, device_type
WITH DATA;
"""

_CREATE_CONVERSION_HOURLY = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS reporting_conversion_hourly AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY period DESC, brand_id, offer_id NULLS LAST, affiliate_id NULLS LAST, country, traffic_source
    ) AS id,
    period,
    brand_id,
    offer_id,
    affiliate_id,
    country,
    traffic_source,
    device_type,
    COUNT(*)                                           AS conversions_total,
    COUNT(*) FILTER (WHERE status = 'approved')        AS conversions_approved,
    COUNT(*) FILTER (WHERE status = 'rejected')        AS conversions_rejected,
    COUNT(*) FILTER (WHERE status = 'hold')            AS conversions_hold,
    SUM(revenue)                                       AS revenue,
    SUM(payout)                                        AS payout
FROM (
    SELECT
        date_trunc('hour', created_at)  AS period,
        brand_id,
        offer_id,
        affiliate_id,
        country,
        sub1                            AS traffic_source,
        {_DEVICE_CASE}                  AS device_type,
        status,
        revenue,
        payout
    FROM tracker_conversion
) _agg
GROUP BY period, brand_id, offer_id, affiliate_id, country, traffic_source, device_type
WITH DATA;
"""

_CREATE_CONVERSION_DAILY = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS reporting_conversion_daily AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY period DESC, brand_id, offer_id NULLS LAST, affiliate_id NULLS LAST, country, traffic_source
    ) AS id,
    period,
    brand_id,
    offer_id,
    affiliate_id,
    country,
    traffic_source,
    device_type,
    COUNT(*)                                           AS conversions_total,
    COUNT(*) FILTER (WHERE status = 'approved')        AS conversions_approved,
    COUNT(*) FILTER (WHERE status = 'rejected')        AS conversions_rejected,
    COUNT(*) FILTER (WHERE status = 'hold')            AS conversions_hold,
    SUM(revenue)                                       AS revenue,
    SUM(payout)                                        AS payout
FROM (
    SELECT
        date_trunc('day', created_at)   AS period,
        brand_id,
        offer_id,
        affiliate_id,
        country,
        sub1                            AS traffic_source,
        {_DEVICE_CASE}                  AS device_type,
        status,
        revenue,
        payout
    FROM tracker_conversion
) _agg
GROUP BY period, brand_id, offer_id, affiliate_id, country, traffic_source, device_type
WITH DATA;
"""

_CREATE_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS reporting_click_hourly_id_uidx    ON reporting_click_hourly (id);
CREATE        INDEX IF NOT EXISTS reporting_click_hourly_brand_idx  ON reporting_click_hourly (brand_id, period DESC);
CREATE        INDEX IF NOT EXISTS reporting_click_hourly_offer_idx  ON reporting_click_hourly (offer_id);

CREATE UNIQUE INDEX IF NOT EXISTS reporting_click_daily_id_uidx     ON reporting_click_daily (id);
CREATE        INDEX IF NOT EXISTS reporting_click_daily_brand_idx   ON reporting_click_daily (brand_id, period DESC);
CREATE        INDEX IF NOT EXISTS reporting_click_daily_offer_idx   ON reporting_click_daily (offer_id);

CREATE UNIQUE INDEX IF NOT EXISTS reporting_conv_hourly_id_uidx     ON reporting_conversion_hourly (id);
CREATE        INDEX IF NOT EXISTS reporting_conv_hourly_brand_idx   ON reporting_conversion_hourly (brand_id, period DESC);

CREATE UNIQUE INDEX IF NOT EXISTS reporting_conv_daily_id_uidx      ON reporting_conversion_daily (id);
CREATE        INDEX IF NOT EXISTS reporting_conv_daily_brand_idx    ON reporting_conversion_daily (brand_id, period DESC);
"""

_DROP_ALL = """
DROP MATERIALIZED VIEW IF EXISTS reporting_click_hourly;
DROP MATERIALIZED VIEW IF EXISTS reporting_click_daily;
DROP MATERIALIZED VIEW IF EXISTS reporting_conversion_hourly;
DROP MATERIALIZED VIEW IF EXISTS reporting_conversion_daily;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0016_click_conversion_brand'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_CREATE_CLICK_HOURLY + _CREATE_CLICK_DAILY
                + _CREATE_CONVERSION_HOURLY + _CREATE_CONVERSION_DAILY
                + _CREATE_INDEXES,
            reverse_sql=_DROP_ALL,
        ),
    ]

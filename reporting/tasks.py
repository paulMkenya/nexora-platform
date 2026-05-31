from project._celery import _celery


@_celery.task(bind=True, max_retries=3)
def refresh_reporting_views(self):
    """Refresh all reporting materialized views concurrently."""
    from django.db import connection

    views = [
        'reporting_click_hourly',
        'reporting_click_daily',
        'reporting_conversion_hourly',
        'reporting_conversion_daily',
    ]
    try:
        with connection.cursor() as cur:
            for view in views:
                cur.execute(f'REFRESH MATERIALIZED VIEW CONCURRENTLY {view}')
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)

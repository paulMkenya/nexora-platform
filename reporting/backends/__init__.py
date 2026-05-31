from django.conf import settings

from .base import AggregationBackend, ReportPage  # noqa: F401


def get_backend() -> AggregationBackend:
    """
    Return the configured aggregation backend.

    Set REPORTING_BACKEND in Django settings to select the implementation:
      'postgres'    — PostgresMatViewBackend (default)
      'clickhouse'  — (future) ClickHouseBackend

    When any brand exceeds ~10M clicks/month, switching to ClickHouse requires
    only: pip-install the driver, implement ClickHouseBackend(AggregationBackend),
    and set REPORTING_BACKEND='clickhouse'.  No view, URL, or serializer code changes.
    """
    backend_name = getattr(settings, 'REPORTING_BACKEND', 'postgres')

    if backend_name == 'postgres':
        from .postgres import PostgresMatViewBackend
        return PostgresMatViewBackend()

    raise ValueError(
        f"Unknown REPORTING_BACKEND '{backend_name}'. "
        "Available: 'postgres'. Future: 'clickhouse'."
    )

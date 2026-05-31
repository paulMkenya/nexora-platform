"""
AggregationBackend abstraction for reporting.

Default implementation: PostgresMatViewBackend (uses Postgres materialized views
refreshed every 5 minutes by a Celery beat task).

Upgrade trigger: when any brand exceeds ~10M clicks/month, switch to ClickHouse
by setting REPORTING_BACKEND='clickhouse' and providing a ClickHouseBackend
implementation that satisfies this interface.  No view or URL code needs to change.

Architecture:
  - REPORTING_BACKEND = 'postgres'  →  PostgresMatViewBackend
  - REPORTING_BACKEND = 'clickhouse'  →  (future) ClickHouseBackend
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ReportPage:
    results: list[dict]
    next_cursor: str | None
    count: int | None = field(default=None)


class AggregationBackend(ABC):
    """Pluggable backend for all aggregated reporting queries."""

    @abstractmethod
    def clicks_report(
        self,
        brand_id: int,
        date_from: datetime,
        date_to: datetime,
        group_by: list[str],
        filters: dict,
        cursor: str | None,
        page_size: int,
    ) -> ReportPage:
        """Aggregated click metrics, grouped and filtered as requested."""

    @abstractmethod
    def conversions_report(
        self,
        brand_id: int,
        date_from: datetime,
        date_to: datetime,
        group_by: list[str],
        filters: dict,
        cursor: str | None,
        page_size: int,
    ) -> ReportPage:
        """Aggregated conversion metrics with status breakdown."""

    @abstractmethod
    def revenue_report(
        self,
        brand_id: int,
        date_from: datetime,
        date_to: datetime,
        group_by: list[str],
        filters: dict,
        cursor: str | None,
        page_size: int,
    ) -> ReportPage:
        """Combined click + conversion revenue with EPC and CR computed fields."""

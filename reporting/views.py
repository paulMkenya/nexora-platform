from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from reporting.backends import get_backend
from reporting.permissions import IsAdvertiserOrNetworkAdmin, get_advertiser, is_network_admin

_PAGE_SIZE = 100
_DATE_FMT = '%Y-%m-%d'


def _parse_date(raw: str | None, default: datetime) -> datetime:
    if not raw:
        return default
    try:
        return datetime.strptime(raw, _DATE_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return default


def _parse_group_by(raw: str | None) -> list[str]:
    valid = {'period', 'offer', 'affiliate', 'country', 'traffic_source', 'device', 'brand'}
    if not raw:
        return ['period']
    return [g.strip() for g in raw.split(',') if g.strip() in valid] or ['period']


def _build_filters(request: Request) -> dict:
    return {
        'offer_id': request.query_params.get('offer_id'),
        'country': request.query_params.get('country'),
        'device': request.query_params.get('device'),
        'traffic_source': request.query_params.get('traffic_source'),
        'affiliate_id': request.query_params.get('affiliate_id'),
    }


def _scope_filters_to_caller(request: Request, filters: dict) -> dict:
    """Restrict the report to what the caller is allowed to see.

    Network admins (and superusers) get brand-wide aggregates unchanged. An
    advertiser is hard-scoped to their own offers within request.brand by
    injecting an ``offer_ids`` allow-list into the filters — this is enforced in
    addition to brand scoping, never instead of it. An advertiser with no offers
    yields an empty list, which the backend treats as "match nothing".
    """
    if is_network_admin(request.user):
        return filters

    advertiser = get_advertiser(request.user)
    if advertiser is not None:
        from offer.models import Offer
        offer_ids = list(
            Offer.objects
            .filter(advertiser=advertiser, brand=request.brand)
            .values_list('id', flat=True)
        )
        filters['offer_ids'] = offer_ids
    return filters


def _etag(brand_id: int, params: dict, results: list) -> str:
    payload = json.dumps({'brand': brand_id, 'params': sorted(params.items()), 'n': len(results)}, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _report_response(request: Request, results: list, next_cursor, serializer_class) -> Response:
    brand = request.brand
    etag = _etag(brand.pk, dict(request.query_params), results)

    if request.META.get('HTTP_IF_NONE_MATCH') == etag:
        return Response(status=304)

    data = serializer_class(results, many=True).data
    body = {'results': data, 'next': next_cursor}
    resp = Response(body)
    resp['ETag'] = etag
    resp['Cache-Control'] = 'private, max-age=60'
    return resp


_COMMON_PARAMS = [
    OpenApiParameter('date_from', str, description='Start date YYYY-MM-DD (default: 7 days ago)'),
    OpenApiParameter('date_to', str, description='End date YYYY-MM-DD (default: today)'),
    OpenApiParameter(
        'group_by', str,
        description='Comma-separated dimensions: period,offer,affiliate,country,traffic_source,device,brand',
    ),
    OpenApiParameter('offer_id', int, required=False),
    OpenApiParameter('country', str, required=False, description='ISO-3166-1 alpha-2'),
    OpenApiParameter('device', str, required=False, description='mobile|tablet|desktop'),
    OpenApiParameter('traffic_source', str, required=False),
    OpenApiParameter('cursor', str, required=False, description='Opaque pagination cursor'),
    OpenApiParameter('page_size', int, required=False, description=f'Max rows (default {_PAGE_SIZE})'),
]


class ClicksReportView(APIView):
    permission_classes = [IsAuthenticated, IsAdvertiserOrNetworkAdmin]

    @extend_schema(parameters=_COMMON_PARAMS, summary='Clicks report')
    def get(self, request: Request) -> Response:
        from reporting.serializers import ClicksReportSerializer

        now = datetime.now(tz=timezone.utc)
        date_from = _parse_date(request.query_params.get('date_from'), now - timedelta(days=7))
        date_to = _parse_date(request.query_params.get('date_to'), now)
        group_by = _parse_group_by(request.query_params.get('group_by'))
        filters = _scope_filters_to_caller(request, _build_filters(request))
        cursor = request.query_params.get('cursor')
        page_size = min(int(request.query_params.get('page_size', _PAGE_SIZE)), 1000)

        backend = get_backend()
        page = backend.clicks_report(
            brand_id=request.brand.pk,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            filters=filters,
            cursor=cursor,
            page_size=page_size,
        )
        return _report_response(request, page.results, page.next_cursor, ClicksReportSerializer)


class ConversionsReportView(APIView):
    permission_classes = [IsAuthenticated, IsAdvertiserOrNetworkAdmin]

    @extend_schema(parameters=_COMMON_PARAMS, summary='Conversions report')
    def get(self, request: Request) -> Response:
        from reporting.serializers import ConversionsReportSerializer

        now = datetime.now(tz=timezone.utc)
        date_from = _parse_date(request.query_params.get('date_from'), now - timedelta(days=7))
        date_to = _parse_date(request.query_params.get('date_to'), now)
        group_by = _parse_group_by(request.query_params.get('group_by'))
        filters = _scope_filters_to_caller(request, _build_filters(request))
        cursor = request.query_params.get('cursor')
        page_size = min(int(request.query_params.get('page_size', _PAGE_SIZE)), 1000)

        backend = get_backend()
        page = backend.conversions_report(
            brand_id=request.brand.pk,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            filters=filters,
            cursor=cursor,
            page_size=page_size,
        )
        return _report_response(request, page.results, page.next_cursor, ConversionsReportSerializer)


class RevenueReportView(APIView):
    permission_classes = [IsAuthenticated, IsAdvertiserOrNetworkAdmin]

    @extend_schema(parameters=_COMMON_PARAMS, summary='Revenue report with EPC and CR')
    def get(self, request: Request) -> Response:
        from reporting.serializers import RevenueReportSerializer

        now = datetime.now(tz=timezone.utc)
        date_from = _parse_date(request.query_params.get('date_from'), now - timedelta(days=7))
        date_to = _parse_date(request.query_params.get('date_to'), now)
        group_by = _parse_group_by(request.query_params.get('group_by'))
        filters = _scope_filters_to_caller(request, _build_filters(request))
        cursor = request.query_params.get('cursor')
        page_size = min(int(request.query_params.get('page_size', _PAGE_SIZE)), 1000)

        backend = get_backend()
        page = backend.revenue_report(
            brand_id=request.brand.pk,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            filters=filters,
            cursor=cursor,
            page_size=page_size,
        )
        return _report_response(request, page.results, page.next_cursor, RevenueReportSerializer)

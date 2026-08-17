"""Inbound lead-submission + pull-status API for affiliates — Affiliate
Inbound API spec §4/§5.2.

Auth: reuses public_api's existing per-user API key scheme (Authorization:
ApiKey <secret>) — an affiliate's key is issued the same way any other
public_api.APIKey is (APIKey.generate(user, name)). No new auth system;
this already satisfies the spec's "header, not query string" preference.

Mirrors op-brandy.com's own shape deliberately: single + batch endpoints,
and the batch response envelope (addedLeads/failedToAddLeads, partial
success) — familiar to affiliates who already integrate with buyer-style
lead APIs, and it's a genuinely good pattern (a batch of 50 shouldn't fail
entirely because one entry has a bad phone number).
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from public_api.authentication import APIKeyAuthentication
from public_api.throttling import APIKeyThrottle

from . import canonical_status
from .models import Lead
from .serializers import (
    AffiliateLeadSubmitSerializer,
    LeadDetailOutSerializer,
    LeadOutSerializer,
    build_attribution,
)
from .tasks import geolocate_lead, maybe_auto_inject

MAX_BATCH_SIZE = 200

# How long a resubmission with the same (affiliate, phone, email) is treated
# as a retry of the same lead rather than a new one, when the affiliate
# doesn't supply their own source_id (spec §4.5: "a source retrying a
# timed-out POST doesn't create duplicates"). source_id, when given, is an
# exact match regardless of window — the affiliate is telling us it's the
# same lead.
DEDUPE_WINDOW_HOURS = 24


class IsAffiliate(BasePermission):
    """The inbound lead API is affiliate-facing only — an API key issued for
    some other purpose (e.g. an advertiser integration) must not be able to
    submit leads."""
    message = 'This endpoint is for affiliate accounts only.'

    def has_permission(self, request, view):
        profile = getattr(request.user, 'profile', None)
        return bool(profile and profile.role == profile.Role.AFFILIATE)


def _resolve_offer(request, offer_id):
    """The Offer `offer_id` refers to, only if it's one this affiliate can
    actually send to — the same single rule every other affiliate surface
    uses (offers_for_affiliate), reused rather than reimplemented. None if it
    doesn't resolve or isn't eligible; the caller treats that as a validation
    failure, never a 500.

    Scoped to the SUBMITTING AFFILIATE, not the request host: posting to
    another brand's domain must not widen what you may submit to. An offer_id
    belonging to another brand — or an unbranded one — resolves to None here
    and comes back as the documented "offer_id does not resolve to an offer
    you can send to" error.
    """
    from affiliate_ui.views.general_views import offers_for_affiliate

    return offers_for_affiliate(request.user).filter(pk=offer_id).first()


def _find_duplicate_lead(user, data):
    """The existing Lead this submission is a retry of, or None if it looks
    genuinely new. See DEDUPE_WINDOW_HOURS."""
    source_id = data.get('source_id')
    if source_id:
        # An explicit source_id is authoritative on its own — a fresh
        # source_id means "this is a distinct lead" even if it shares a
        # phone/email with an older submission, so it must NOT fall through
        # to the phone+email window check below.
        return Lead.objects.filter(affiliate=user, source_id=source_id).order_by('-created_at').first()
    window_start = timezone.now() - timedelta(hours=DEDUPE_WINDOW_HOURS)
    return (
        Lead.objects.filter(affiliate=user, phone=data['phone'], email=data['email'], created_at__gte=window_start)
        .order_by('-created_at').first()
    )


def _create_lead(request, data, *, offer):
    lead = Lead.objects.create(
        brand=getattr(request, 'brand', None),
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        affiliate=request.user,
        offer=offer,
        first_name=data['first_name'],
        last_name=data['last_name'],
        email=data['email'],
        phone=data['phone'],
        vertical=data['vertical'],
        source_id=data['source_id'],
        country_iso2=data.get('country', ''),
        language=data.get('language', ''),
        attribution=build_attribution(data),
        user_agent=data.get('user_agent', ''),
        # The affiliate's own submitted `ip` (their system may hold the real
        # consumer IP — spec §4.3) wins over the connecting request's own
        # remote address, which for this channel is just the affiliate's
        # server, not the consumer's.
        ip=data.get('ip') or request.META.get('REMOTE_ADDR', '') or None,
        raw_payload=data,
    )
    # NOTE: geolocation is a best-effort fallback for this channel — see
    # NOTE below and leadgen/README.md's geolocation section. sync_buyer_
    # statuses' countryIso2 backfill (sourced from the buyer) is the more
    # reliable signal for affiliate-submitted leads when `country` isn't
    # supplied directly.
    geolocate_lead.delay(lead.pk)
    maybe_auto_inject(lead)
    return lead


def _ignored_fields(serializer, raw):
    """Top-level keys the caller sent that this contract has no field for.

    DRF drops unknown keys silently, so before this existed an affiliate
    could POST `MPC_3` or `lg`, get a 201 back, and have no way to discover
    that the value never left their own server — the failure mode this whole
    endpoint is least able to detect for them. Reporting the names back turns
    a silent drop into something visible on the very first test call.

    Advisory only: unknown keys are still ignored, never a 400. Rejecting
    them would break any affiliate who already sends a field we don't read,
    and would make every future field we add a breaking change for them.
    """
    if not isinstance(raw, dict):
        return []
    return sorted(set(raw) - set(serializer.fields))


def _submit_response(serializer, raw, lead):
    """The lead body, plus `ignored_fields` when — and only when — the caller
    sent something we couldn't use. Absent on a clean submission, so the
    common case is unchanged for existing integrations."""
    body = dict(LeadOutSerializer(lead).data)
    ignored = _ignored_fields(serializer, raw)
    if ignored:
        body['ignored_fields'] = ignored
    return body


def _submit_one(request, data):
    """(lead, created) for one already-validated submission — created=False
    means this was a dedupe hit (the ORIGINAL lead, per spec §4.5, not a new
    row), created=True means a fresh Lead was made. Returns (None, None,
    error_detail) if offer_id doesn't resolve."""
    offer = _resolve_offer(request, data['offer_id'])
    if offer is None:
        return None, None, 'offer_id does not resolve to an offer you can send to.'

    duplicate = _find_duplicate_lead(request.user, data)
    if duplicate is not None:
        return duplicate, False, None

    return _create_lead(request, data, offer=offer), True, None


class LeadSubmitView(APIView):
    """POST /api/leads/submit — one lead."""

    # doc_purpose is what puts an endpoint in the generated affiliate doc.
    # leadgen.api_doc walks this app's URL conf for views carrying it, so a
    # newly routed endpoint documents itself and the doc cannot list a path
    # that isn't really wired (spec §6.3's anti-drift rule). Omit it on
    # anything affiliates shouldn't be told about.
    doc_purpose = 'Submit one lead.'
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def post(self, request):
        serializer = AffiliateLeadSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lead, created, error = _submit_one(request, serializer.validated_data)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            _submit_response(serializer, request.data, lead),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class LeadBatchSubmitView(APIView):
    """POST /api/leads/submit/batch — up to 200 leads, partial success."""

    doc_purpose = f'Submit up to {MAX_BATCH_SIZE} leads in one call; partial success.'
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def post(self, request):
        items = request.data.get('leads')
        if not isinstance(items, list) or not items:
            return Response(
                {'detail': '"leads" must be a non-empty list.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(items) > MAX_BATCH_SIZE:
            return Response(
                {'detail': f'Maximum {MAX_BATCH_SIZE} leads per batch.'}, status=status.HTTP_400_BAD_REQUEST)

        added, failed = [], []
        for raw in items:
            item_serializer = AffiliateLeadSubmitSerializer(data=raw)
            if not item_serializer.is_valid():
                failed.append({'input': raw, 'errors': item_serializer.errors})
                continue

            lead, _created, error = _submit_one(request, item_serializer.validated_data)
            if error:
                failed.append({'input': raw, 'errors': {'offer_id': [error]}})
                continue
            added.append(_submit_response(item_serializer, raw, lead))

        response_status = status.HTTP_201_CREATED if added else status.HTTP_400_BAD_REQUEST
        return Response({'addedLeads': added, 'failedToAddLeads': failed}, status=response_status)


class _LeadPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class LeadListView(APIView):
    """GET /api/leads — the calling affiliate's own submitted leads (spec
    §5.2's pull/reconcile path). Filters: status (canonical_status),
    source_id, ids (comma-separated), updated_since (ISO datetime) — same
    ownership scoping (affiliate=request.user) as every other view here, the
    same rule that keeps affiliate B from ever seeing affiliate A's leads."""

    doc_purpose = 'Pull your own leads — filter by status, source_id, ids, updated_since.'

    # Declared next to the code that implements them, and rendered into the
    # affiliate doc by leadgen.api_doc — same anti-drift rule as doc_purpose:
    # a filter that isn't really parsed below cannot be documented, and one
    # that is added below without a row here shows up as undocumented.
    doc_filters = [
        {'name': 'status', 'example': 'ftd',
         'purpose': 'Exact canonical status. Use ftd for First Time Deposit conversions.'},
        {'name': 'source_id', 'example': 'your-own-tracking-id',
         'purpose': 'Exact match on the source_id you submitted with the lead.'},
        {'name': 'ids', 'example': '1024,1025,1031',
         'purpose': 'Comma-separated Nexora lead ids. Non-numeric entries are ignored.'},
        {'name': 'updated_since', 'example': '2026-01-01T00:00:00Z',
         'purpose': 'ISO-8601. Returns leads whose updated_at is >= this — the reconcile filter. '
                    'updated_at moves on every state change, including a status change, so a lead '
                    'that converted since your last poll comes back here. An unparseable value is '
                    'ignored rather than erroring, so always check the timestamps you get back.'},
        {'name': 'page', 'example': '2',
         'purpose': 'Page number, 1-based. Prefer following the "next" URL in the response.'},
        {'name': 'page_size', 'example': '200',
         'purpose': f'Results per page. Default {_LeadPagination.page_size}, '
                    f'maximum {_LeadPagination.max_page_size}.'},
    ]
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def get(self, request):
        qs = Lead.objects.filter(affiliate=request.user).order_by('-created_at')

        status_filter = request.GET.get('status')
        if status_filter:
            qs = qs.filter(canonical_status=status_filter)

        source_id = request.GET.get('source_id')
        if source_id:
            qs = qs.filter(source_id=source_id)

        ids = request.GET.get('ids')
        if ids:
            id_list = [i.strip() for i in ids.split(',') if i.strip().isdigit()]
            qs = qs.filter(pk__in=id_list)

        updated_since = request.GET.get('updated_since')
        if updated_since:
            parsed = parse_datetime(updated_since)
            if parsed:
                qs = qs.filter(updated_at__gte=parsed)

        paginator = _LeadPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(LeadOutSerializer(page, many=True).data)


class LeadDetailView(APIView):
    """GET /api/leads/<id> — one lead's current status + timeline snapshot.
    404s (never a 403) for another affiliate's lead — existence isn't
    revealed either, same posture as every other ownership-scoped lookup."""

    doc_purpose = 'One lead, including its full status timeline.'
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def get(self, request, pk):
        lead = Lead.objects.filter(pk=pk, affiliate=request.user).first()
        if lead is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(LeadDetailOutSerializer(lead).data)


class LeadStatusListView(APIView):
    """GET /api/leads/statuses — the canonical status vocabulary (spec
    §4.1's optional endpoint), so a source can display/localize the
    statuses it'll see without hand-copying leadgen/canonical_status.py."""

    doc_purpose = 'The canonical status vocabulary, as JSON.'
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def get(self, request):
        return Response([{'value': value, 'label': label} for value, label in canonical_status.CHOICES])

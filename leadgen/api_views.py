"""Inbound lead-submission API for affiliates.

Auth: reuses public_api's existing per-user API key scheme (Authorization:
ApiKey <secret>) — an affiliate's key is issued the same way any other
public_api.APIKey is (APIKey.generate(user, name)). No new auth system.

Mirrors op-brandy.com's own shape deliberately: single + batch endpoints,
and the batch response envelope (addedLeads/failedToAddLeads, partial
success) — familiar to affiliates who already integrate with buyer-style
lead APIs, and it's a genuinely good pattern (a batch of 50 shouldn't fail
entirely because one entry has a bad phone number).
"""
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from public_api.authentication import APIKeyAuthentication
from public_api.throttling import APIKeyThrottle

from .models import Lead
from .serializers import LeadOutSerializer, LeadSubmitSerializer
from .tasks import geolocate_lead, maybe_auto_inject

MAX_BATCH_SIZE = 200


class IsAffiliate(BasePermission):
    """The inbound lead API is affiliate-facing only — an API key issued for
    some other purpose (e.g. an advertiser integration) must not be able to
    submit leads."""
    message = 'This endpoint is for affiliate accounts only.'

    def has_permission(self, request, view):
        profile = getattr(request.user, 'profile', None)
        return bool(profile and profile.role == profile.Role.AFFILIATE)


def _create_lead(request, data):
    lead = Lead.objects.create(
        brand=getattr(request, 'brand', None),
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        affiliate=request.user,
        first_name=data['first_name'],
        last_name=data['last_name'],
        email=data['email'],
        phone=data['phone'],
        vertical=data['vertical'],
        source_id=data['source_id'],
        ip=request.META.get('REMOTE_ADDR', '') or None,
        raw_payload=data,
    )
    # NOTE: for this channel `ip` is the affiliate's own submitting system,
    # not necessarily the end consumer's — geolocating it is a best-effort
    # fallback only. sync_buyer_statuses' countryIso2 backfill (sourced from
    # the buyer, who derives it from the phone number) is the more reliable
    # signal for affiliate-submitted leads.
    geolocate_lead.delay(lead.pk)
    maybe_auto_inject(lead)
    return lead


class LeadSubmitView(APIView):
    """POST /api/leads/submit — one lead."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def post(self, request):
        serializer = LeadSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = _create_lead(request, serializer.validated_data)
        return Response(LeadOutSerializer(lead).data, status=status.HTTP_201_CREATED)


class LeadBatchSubmitView(APIView):
    """POST /api/leads/submit/batch — up to 200 leads, partial success."""

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
            item_serializer = LeadSubmitSerializer(data=raw)
            if item_serializer.is_valid():
                lead = _create_lead(request, item_serializer.validated_data)
                added.append(LeadOutSerializer(lead).data)
            else:
                failed.append({'input': raw, 'errors': item_serializer.errors})

        response_status = status.HTTP_201_CREATED if added else status.HTTP_400_BAD_REQUEST
        return Response({'addedLeads': added, 'failedToAddLeads': failed}, status=response_status)


class LeadListView(APIView):
    """GET /api/leads — the calling affiliate's own submitted leads."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def get(self, request):
        qs = Lead.objects.filter(affiliate=request.user).order_by('-created_at')[:200]
        return Response(LeadOutSerializer(qs, many=True).data)

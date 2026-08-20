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
from .models import AffiliatePostbackConfig, Lead
from .requirements import missing_buyer_requirements
from .serializers import (
    AffiliateLeadSubmitSerializer,
    PostbackConfigSerializer,
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


# WHY A LEAD'S BRAND COMES FROM ITS OFFER, NOT FROM request.brand
# ================================================================
# BrandMiddleware resolves request.brand from the HOST HEADER and falls back to
# the default brand when no domain matches. The inbound API is authenticated by
# API key and is not host-gated, so request.brand is attacker- and accident-
# controlled: any host that is not exactly a tenant's own domain — another
# tenant's domain, an IP, a bare apex, a proxy rewrite, a typo — resolves to the
# DEFAULT brand.
#
# Stamping that onto the Lead put a tenant's lead inside another tenant:
# Lead.brand is what leadgen.routing.resolve_buyer_chain filters rules on, so the
# lead was routed by the WRONG tenant's rules, to the WRONG tenant's buyer. The
# layer-3 guard in services.start_injection does not catch it — it compares
# lead.brand_id to buyer.brand_id, and by that point both agree on the wrong
# brand. It is designed to stop a RULE reaching across brands, not a lead that
# was mis-stamped before routing ever ran.
#
# Happened in production: lead 28 (2026-08-06) came from a ChainPulse affiliate,
# for a ChainPulse offer, and landed in brand 6. It was never delivered only
# because that brand's single buyer has auto_inject off — luck, not design.
#
# offer.brand is the right source and is safe by construction: _resolve_offer
# admits only offers from offers_for_affiliate(request.user), which filters on
# the AFFILIATE's own brand and excludes null-brand offers entirely (Paul's
# brand-only ruling, 2026-08-04). So offer.brand is always the affiliate's brand
# and is never None. This also makes both intake channels agree — the hosted
# landing page has always used offer.brand (public_views.capture_lead).


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
        # THE OFFER'S brand, never request.brand — see _lead_brand_note below.
        brand=offer.brand,
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


def _candidate_lead(request, data, *, offer):
    """An UNSAVED Lead carrying exactly the attributes routing matches on
    (brand, offer, affiliate, country, vertical, intake channel), so a
    submission can be resolved to its destination and checked against that
    buyer's requirements BEFORE any row is written.

    Deliberately not _create_lead()'s twin: it exists to be thrown away, and
    building only the routing keys keeps it obvious that nothing here is the
    lead that eventually gets saved.
    """
    return Lead(
        # Must match _create_lead's own choice exactly, or the gate would check
        # the requirements of a buyer this lead is never going to reach.
        brand=offer.brand,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        affiliate=request.user,
        offer=offer,
        country_iso2=data.get('country', ''),
        vertical=data['vertical'],
    )


def _buyer_requirement_errors(request, data, *, offer):
    """DRF-shaped field errors for anything this lead's DESTINATION requires
    and this submission didn't supply, or None when it is fine to accept.

    See leadgen.requirements: our inbound contract is not the buyer's, and
    the affiliate can only see ours. Rejecting here — naming the field, on
    the call that submitted it — is the difference between an integrator
    fixing one line and a lead vanishing after a 201.
    """
    missing = missing_buyer_requirements(_candidate_lead(request, data, offer=offer))
    if not missing:
        return None
    return {
        name: [
            f'This field is required for offer {offer.pk} — the buyer it routes to '
            f'rejects leads without it.'
        ]
        for name in missing
    }


def _submit_one(request, data):
    """(lead, created, errors) for one already-validated submission.

    created=False means this was a dedupe hit (the ORIGINAL lead, per spec
    §4.5, not a new row); created=True means a fresh Lead was made.

    `errors` is None on success, otherwise a dict already in the shape both
    views return it in: {'detail': str} for a whole-request failure (the body
    the generated doc quotes for offer_id), {field: [msg]} for a per-field
    one, matching DRF's own validation errors so an integrator parses one
    shape rather than two.
    """
    offer = _resolve_offer(request, data['offer_id'])
    if offer is None:
        return None, None, {'detail': 'offer_id does not resolve to an offer you can send to.'}

    duplicate = _find_duplicate_lead(request.user, data)
    if duplicate is not None:
        # A dedupe hit returns the ORIGINAL lead and injects nothing, so the
        # destination's requirements are not this submission's problem — it
        # never reaches a buyer. Checking here would turn a harmless retry
        # into a 400.
        return duplicate, False, None

    errors = _buyer_requirement_errors(request, data, offer=offer)
    if errors:
        return None, None, errors

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

        lead, created, errors = _submit_one(request, serializer.validated_data)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

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

            lead, _created, errors = _submit_one(request, item_serializer.validated_data)
            if errors:
                failed.append({'input': raw, 'errors': errors})
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


# --- Postback self-service over the API (spec §5.1) ---------------------------
#
# WHY THIS EXISTS. Registering a postback used to require a browser session on
# /partner/postbacks/. But the person wiring up a postback is a DEVELOPER at the
# traffic source, and they are typically not the person holding the portal
# password — so the integration stalled on a human handoff, and until it was
# done every status change was invisible to the affiliate (they had to poll).
# Their API key already proves who they are; that is enough to manage their own
# postbacks.
#
# "WITHOUT LOGGING IN" MEANS WITHOUT A PORTAL SESSION — NOT UNAUTHENTICATED.
# These endpoints carry exactly the same authentication as lead submission
# (APIKeyAuthentication + IsAffiliate). An anonymous registration endpoint would
# let anybody point a postback carrying another affiliate's lead data — email,
# phone, status — at a server they control. Every view here scopes its queryset
# to affiliate=request.user, the same ownership rule the lead endpoints use.


class _PostbackScopedMixin:
    """Auth + ownership, identical to the lead endpoints. The queryset is
    filtered by the AUTHENTICATED USER, never by an id from the request, so
    there is no object here that one affiliate can reach by guessing another's
    primary key — a 404 is what a wrong id gets, not someone else's config."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated, IsAffiliate]
    throttle_classes = [APIKeyThrottle]

    def get_queryset(self):
        return AffiliatePostbackConfig.objects.filter(affiliate=self.request.user)


class PostbackListCreateView(_PostbackScopedMixin, APIView):
    """GET/POST /api/postbacks — list your postbacks, or register one."""

    doc_purpose = 'List your postback URLs, or register a new one.'

    def get(self, request):
        configs = self.get_queryset().order_by('-created_at')
        return Response({'results': PostbackConfigSerializer(configs, many=True).data})

    def post(self, request):
        serializer = PostbackConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = serializer.save(affiliate=request.user)

        # The ONLY moment the signing secret is ever readable — same show-once
        # contract as an API key. It is deliberately absent from the serializer,
        # so it has to be added here explicitly rather than leaking by default.
        body = dict(serializer.data)
        body['secret'] = config.secret
        body['secret_note'] = (
            'Shown once. Store it now — it signs every delivery as '
            'X-Nexora-Signature: sha256=<hmac> and cannot be retrieved again.'
        )
        return Response(body, status=status.HTTP_201_CREATED)


class PostbackDetailView(_PostbackScopedMixin, APIView):
    """GET/PATCH/DELETE /api/postbacks/<id> — inspect, update or remove one."""

    doc_purpose = 'Inspect, update or delete one of your postback URLs.'

    def _get_object(self, request, pk):
        from django.shortcuts import get_object_or_404
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get(self, request, pk):
        return Response(PostbackConfigSerializer(self._get_object(request, pk)).data)

    def patch(self, request, pk):
        config = self._get_object(request, pk)
        serializer = PostbackConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        """Deactivates rather than destroys. PostbackDelivery rows FK to this
        config and are the audit trail of what we sent and what came back —
        "every postback attempt logged" (spec §5.1). A hard delete would
        cascade that history away on a whim, and the affiliate's own delivery
        log is exactly the evidence a billing dispute turns on.
        """
        config = self._get_object(request, pk)
        config.is_active = False
        config.save(update_fields=['is_active', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

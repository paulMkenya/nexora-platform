"""Financial-record summaries and hard-delete eligibility.

Hard (permanent) deletion is only ever allowed for a *genuinely empty* entity —
one with no financial history. This module is the single source of truth for
"does this entity carry financial records?" so the UI and the delete views agree.

Financial records are, by entity:

  * Affiliate  — conversions earned, payout requests made.
  * Advertiser — conversions on their offers, wallet transactions / top-ups.
  * Brand      — any of the above across the brand (its conversions, its
                 affiliates' payout requests, its advertisers' wallet activity).

Archiving never consults this — it is always allowed and always reversible.
Only hard delete is guarded.
"""


# ── affiliate ────────────────────────────────────────────────────────────────

def affiliate_financials(profile):
    """Financial-record summary + hard-delete eligibility for an affiliate."""
    from payouts.models import PayoutRequest
    from tracker.models import Conversion

    user = profile.user
    conversions = Conversion.objects.filter(affiliate=user).count()
    payout_requests = PayoutRequest.objects.filter(affiliate=user).count()
    has_financial = bool(conversions or payout_requests)

    parts = []
    if conversions:
        parts.append(f'{conversions} conversion{"s" if conversions != 1 else ""}')
    if payout_requests:
        parts.append(f'{payout_requests} payout request{"s" if payout_requests != 1 else ""}')

    return {
        'conversions': conversions,
        'payout_requests': payout_requests,
        'wallet_transactions': 0,
        'has_financial': has_financial,
        'can_hard_delete': not has_financial,
        'summary': ', '.join(parts) if parts else 'No financial records',
        'block_reason': (
            f'has {", ".join(parts)} — archive only' if has_financial else ''
        ),
    }


# ── advertiser ───────────────────────────────────────────────────────────────

def advertiser_financials(advertiser):
    """Financial-record summary + hard-delete eligibility for an advertiser."""
    from billing.models import WalletTopUp, WalletTransaction
    from offer.models import Offer
    from tracker.models import Conversion

    conversions = Conversion.objects.filter(offer__advertiser=advertiser).count()
    wallet_txns = WalletTransaction.objects.filter(
        wallet__advertiser=advertiser).count()
    wallet_topups = WalletTopUp.objects.filter(
        wallet__advertiser=advertiser).count()
    offers = Offer.objects.filter(advertiser=advertiser).count()
    wallet_activity = wallet_txns + wallet_topups
    has_financial = bool(conversions or wallet_activity)

    parts = []
    if conversions:
        parts.append(f'{conversions} conversion{"s" if conversions != 1 else ""}')
    if wallet_activity:
        parts.append(f'{wallet_activity} wallet transaction{"s" if wallet_activity != 1 else ""}')

    return {
        'conversions': conversions,
        'wallet_transactions': wallet_activity,
        'offers': offers,
        'has_financial': has_financial,
        'can_hard_delete': not has_financial,
        'summary': ', '.join(parts) if parts else 'No financial records',
        'block_reason': (
            f'has {", ".join(parts)} — archive only' if has_financial else ''
        ),
    }


# ── brand ────────────────────────────────────────────────────────────────────

def brand_financials(brand):
    """Financial-record summary + hard-delete eligibility for a brand.

    A brand is hard-deletable only when nothing under it carries financial data:
    no conversions, no affiliate payout requests, no advertiser wallet activity.
    The default brand is never deletable (guarded separately in the view).
    """
    from billing.models import WalletTopUp, WalletTransaction
    from offer.models import Advertiser, Offer
    from payouts.models import PayoutRequest
    from tracker.models import Conversion
    from user_profile.models import Profile

    conversions = Conversion.objects.filter(brand=brand).count()
    payout_requests = PayoutRequest.objects.filter(
        affiliate__profile__brand=brand).count()
    wallet_activity = (
        WalletTransaction.objects.filter(wallet__advertiser__brand=brand).count()
        + WalletTopUp.objects.filter(wallet__advertiser__brand=brand).count()
    )
    has_financial = bool(conversions or payout_requests or wallet_activity)

    parts = []
    if conversions:
        parts.append(f'{conversions} conversion{"s" if conversions != 1 else ""}')
    if payout_requests:
        parts.append(f'{payout_requests} payout request{"s" if payout_requests != 1 else ""}')
    if wallet_activity:
        parts.append(f'{wallet_activity} wallet transaction{"s" if wallet_activity != 1 else ""}')

    return {
        'conversions': conversions,
        'payout_requests': payout_requests,
        'wallet_transactions': wallet_activity,
        'advertisers': Advertiser.objects.filter(brand=brand).count(),
        'affiliates': Profile.objects.filter(brand=brand).count(),
        'offers': Offer.objects.filter(brand=brand).count(),
        'has_financial': has_financial,
        'can_hard_delete': not has_financial and not brand.is_default,
        'is_default': brand.is_default,
        'summary': ', '.join(parts) if parts else 'No financial records',
        'block_reason': (
            'default brand — cannot be deleted' if brand.is_default
            else (f'has {", ".join(parts)} — archive only' if has_financial else '')
        ),
    }


def brand_delete_cleanup(brand):
    """External cleanup still required after a brand hard-delete.

    The DB delete SET_NULLs the brand FK on its offers/advertisers/affiliates/
    conversions (orphaning, never destroying them). Everything *outside* the
    database — the NPM proxy hosts and DNS records for the brand's domains — must
    be removed by hand; this returns those instructions rather than performing
    them (we never call NPM or touch DNS automatically).
    """
    fin = brand_financials(brand)
    domains = [d for d in (brand.primary_domain, brand.tracking_domain) if d]
    return {
        'orphaned': {
            'offers': fin['offers'],
            'advertisers': fin['advertisers'],
            'affiliates': fin['affiliates'],
            'conversions': fin['conversions'],
        },
        'domains': domains,
        'instructions': [
            f'Remove the Nginx Proxy Manager proxy host(s) for: {", ".join(domains) or "(none)"}',
            f'Delete the DNS A/CNAME records pointing these domains at the platform: {", ".join(domains) or "(none)"}',
            'These steps are NOT automated — perform them in NPM (http://127.0.0.1:81) and your DNS provider.',
        ],
    }

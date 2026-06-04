"""Brand-aware tracking-link construction.

Every link shown to a brand's affiliate or advertiser (click links, postback
URLs, etc.) must be hosted on **that brand's** tracking domain — never the
underlying platform domain (``TRACKER_URL``). Showing ``t.cloudtrade.pro`` on a
CCS page (or vice versa) leaks the platform and breaks white-label isolation.

Resolution order (most specific wins):
  1. the supplied brand's ``tracking_domain`` (e.g. the *offer's* brand),
  2. the current request's brand ``tracking_domain`` (the domain the user is on),
  3. the global ``settings.TRACKER_URL`` (single-brand / legacy fallback).
"""

from django.conf import settings


def _normalize_base(value: str) -> str:
    """Turn a bare host or a URL into an ``https`` base URL with no trailing slash.

    Brand ``tracking_domain`` values are stored as bare hosts
    (``t.cloudtradesystems.com``); ``TRACKER_URL`` already carries a scheme.
    """
    value = (value or '').strip()
    if not value:
        return ''
    if not value.startswith(('http://', 'https://')):
        value = f'https://{value}'
    return value.rstrip('/')


def tracking_base_url(brand=None, request=None) -> str:
    """Resolve the tracking base URL (scheme + host) for a brand-facing link.

    See module docstring for the resolution order. Never returns a less specific
    brand's domain when a more specific one is available, preserving isolation.
    """
    base = _normalize_base(getattr(brand, 'tracking_domain', '')) if brand else ''
    if base:
        return base

    req_brand = getattr(request, 'brand', None)
    base = _normalize_base(getattr(req_brand, 'tracking_domain', '')) if req_brand else ''
    if base:
        return base

    return _normalize_base(settings.TRACKER_URL)


def affiliate_click_link(offer, pid, request=None) -> str:
    """Affiliate-facing click URL for *offer*, hosted on the offer's brand domain.

    The query format is unchanged (``/click?offer_id=<id>&pid=<affiliate uid>``);
    only the host is resolved per brand.
    """
    base = tracking_base_url(brand=getattr(offer, 'brand', None), request=request)
    return f"{base}/click?offer_id={offer.id}&pid={pid}"

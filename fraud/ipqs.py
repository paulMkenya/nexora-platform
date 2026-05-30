"""
IPQualityScore proxy/datacenter/fraud lookup.
Only active when IPQS_API_KEY is set in settings — disabled by default.
"""
import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

IPQS_BASE = 'https://www.ipqualityscore.com/api/json/ip'
TIMEOUT = 3


def lookup(ip: str) -> Optional[dict]:
    """
    Return IPQS result dict with keys: proxy, vpn, tor, bot_status,
    is_crawler, fraud_score, ISP, organization, host, country_code, etc.
    Returns None when the feature is disabled or on any error.
    """
    api_key = getattr(settings, 'IPQS_API_KEY', '')
    if not api_key:
        return None

    try:
        url = f'{IPQS_BASE}/{api_key}/{ip}'
        resp = requests.get(url, params={'strictness': 1, 'fast': 1}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not data.get('success'):
            logger.warning('IPQS non-success for %s: %s', ip, data.get('message'))
            return None
        return data
    except Exception as exc:
        logger.warning('IPQS lookup failed for %s: %s', ip, exc)
        return None


def enrich_click(click_id: str) -> None:
    """
    Pull IPQS data and update is_proxy / is_datacenter / is_bot on the Click.
    No-op when IPQS_API_KEY is not set.
    """
    from tracker.models import Click
    try:
        click = Click.objects.get(pk=click_id)
    except Click.DoesNotExist:
        return

    data = lookup(click.ip or '')
    if data is None:
        return

    updates = {
        'is_proxy': bool(data.get('proxy') or data.get('vpn') or data.get('tor')),
        'is_datacenter': bool(data.get('host', '').lower() in ('datacenter', 'hosting')),
        'is_bot': bool(data.get('bot_status') or data.get('is_crawler')),
    }
    Click.objects.filter(pk=click_id).update(**updates)

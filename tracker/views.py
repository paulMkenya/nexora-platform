import hashlib
import hmac as _hmac
import uuid
from typing import Dict, Any

from django.conf import settings
from django.http import HttpResponse, HttpRequest
from django.shortcuts import redirect

from tracker.dao import TrackerCache
from tracker.models import HMAC_FAIL, HMAC_MISSING, HMAC_OK, HMAC_SKIP, conversion_statuses
from tracker.tasks.click import click as click_task
from tracker.tasks.conversion import conversion


# ── helpers ────────────────────────────────────────────────────────────────

def get_client_ip(request: HttpRequest) -> str:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def replace_macro(url: str, context: Dict[str, Any]) -> str:
    url = url.replace('{click_id}', context['click_id'])
    url = url.replace('{clickid}', context['click_id'])
    url = url.replace('{pid}', context['pid'])
    url = url.replace('{fb_id}', context['fb_id'])
    return url


# ── HMAC verification ──────────────────────────────────────────────────────

def _canonical(params: dict) -> str:
    """Sorted key=value string excluding the 'sig' param."""
    return '&'.join(
        f'{k}={v}' for k, v in sorted(params.items()) if k != 'sig'
    )


def _verify_sig(secret: str, params: dict, sig: str) -> bool:
    expected = _hmac.new(
        secret.encode('utf-8'),
        _canonical(params).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(sig.lower(), expected.lower())


def _check_postback_hmac(request, click_id):
    """
    Look up the advertiser via click → offer → advertiser, then verify HMAC.
    Returns (advertiser_or_None, hmac_status_string).
    Never raises — logging must not crash the tracking endpoint.
    """
    from offer.models import AdvertiserPostbackKey
    from tracker.models import Click

    advertiser = None
    try:
        click = (
            Click.objects
            .select_related('offer__advertiser__postback_key')
            .get(pk=click_id)
        )
        if click.offer and click.offer.advertiser:
            advertiser = click.offer.advertiser
    except Exception:
        return None, HMAC_SKIP

    try:
        secret = advertiser.postback_key.secret
    except AdvertiserPostbackKey.DoesNotExist:
        return advertiser, HMAC_SKIP

    sig = request.GET.get('sig', '')
    if not sig:
        return advertiser, HMAC_MISSING

    # request.GET.dict() gives scalar values; dict(request.GET) gives lists.
    if _verify_sig(secret, request.GET.dict(), sig):
        return advertiser, HMAC_OK
    return advertiser, HMAC_FAIL


def _log_postback(advertiser, request, hmac_status, response_code, note=''):
    """Write one InboundPostbackLog row. Swallows all exceptions."""
    try:
        from tracker.models import InboundPostbackLog
        InboundPostbackLog.objects.create(
            advertiser=advertiser,
            click_id=(request.GET.get('click_id') or '')[:64],
            status_param=(request.GET.get('status') or '')[:20],
            sum_param=(request.GET.get('sum') or '')[:32],
            query_string=request.META.get('QUERY_STRING', '')[:1000],
            hmac_status=hmac_status,
            response_code=response_code,
            note=note[:255],
        )
    except Exception:
        pass


# ── views ──────────────────────────────────────────────────────────────────

def click(request):
    offer_id = request.GET.get('offer_id')
    pid = request.GET.get('pid')
    if not offer_id or not pid:
        return HttpResponse('Missing parameters', status=400)

    offer_data = TrackerCache.get_offer(offer_id)
    if not offer_data:
        return HttpResponse(status=404)

    click_id = uuid.uuid4().hex

    data = {
        'click_id': click_id,
        'offer_id': offer_id,
        'pid': pid,
        'ip': get_client_ip(request),
        'ua': request.META.get('HTTP_USER_AGENT', ''),
        'sub1': request.GET.get('sub1', ''),
        'sub2': request.GET.get('sub2', ''),
        'sub3': request.GET.get('sub3', ''),
        'sub4': request.GET.get('sub4', ''),
        'sub5': request.GET.get('sub5', ''),
    }

    click_task.delay(data)

    context = {
        'click_id': click_id,
        'pid': pid,
        'fb_id': request.GET.get('fb_id', ''),
    }

    # If offer is wired to an MMP, send the click to the MMP tracking URL
    if offer_data.get('mmp_click_template') and offer_data.get('mmp_app_id'):
        from mmp.format import build_mmp_click_url
        url = build_mmp_click_url(
            click_template=offer_data['mmp_click_template'],
            click_id=click_id,
            app_id=offer_data['mmp_app_id'],
            affiliate_id=pid,
            offer_id=offer_id,
        )
    else:
        url = replace_macro(offer_data['tracking_link'], context)

    return redirect(url)


def postback(request):
    click_id = request.GET.get('click_id')
    goal     = request.GET.get('goal', '1')
    status   = request.GET.get('status')

    try:
        sum_ = float(request.GET.get('sum', '') or 0)
    except (ValueError, TypeError):
        sum_ = 0.0

    if not click_id:
        _log_postback(None, request, HMAC_SKIP, 400, 'Missing click_id')
        return HttpResponse('Missing click_id', status=400)

    # ── HMAC verification ──────────────────────────────────────────────────
    advertiser, hmac_status = _check_postback_hmac(request, click_id)
    enforce = getattr(settings, 'ENFORCE_POSTBACK_HMAC', False)

    if enforce and hmac_status not in (HMAC_OK, HMAC_SKIP):
        _log_postback(advertiser, request, hmac_status, 401, 'Rejected by HMAC policy')
        return HttpResponse('Invalid or missing HMAC signature', status=401)

    # ── queue conversion task (existing behaviour unchanged) ───────────────
    data = {'click_id': click_id, 'goal': goal, 'sum': sum_}
    valid_statuses = {s for s, _ in conversion_statuses}
    if status in valid_statuses:
        data['status'] = status

    conversion.delay(data)

    _log_postback(advertiser, request, hmac_status, 200)
    return HttpResponse('Conversion logged')

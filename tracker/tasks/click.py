import logging

from django.contrib.auth import get_user_model
from offer.models import Offer
from project._celery import _celery
from tracker.models import Click
from ext import geoip
from ext.ipapi import API, Err as IpstackErr, Response as IpLookup

logger = logging.getLogger(__name__)


def resolve_click_brand(offer_id, request_brand_id):
    """Decide which brand a click belongs to.

    The **offer's** brand is authoritative (a click is for that brand's offer no
    matter which domain it physically arrived on). If the tracking domain it came
    in on belongs to a *different* brand, we log the mismatch and still attribute
    by the offer's brand — never silently cross-attributing. When the offer has
    no brand (legacy / network-wide), fall back to the tracking domain's brand.
    """
    offer_brand_id = (
        Offer.objects.filter(pk=offer_id).values_list('brand_id', flat=True).first()
    )

    if offer_brand_id and request_brand_id and offer_brand_id != request_brand_id:
        logger.warning(
            "click brand mismatch: offer %s belongs to brand %s but click "
            "arrived on brand %s; attributing to the offer's brand",
            offer_id, offer_brand_id, request_brand_id,
        )

    return offer_brand_id or request_brand_id


# def detect_country(ip: str) -> str:
#     reader = geolite2.reader()
#     ip_info = reader.get(ip) or {}
#     country = ip_info.get("country", {}).get("iso_code", "")
#     return country


def lookup_ip(ip: str) -> IpLookup:
    """Country + network for a click IP.

    ip-api first (it also gives the ASN/ISP that carrier targeting needs). If it
    fails — rate limit, timeout, private IP — fall back to the local GeoLite2
    country DB so the click still gets a country; otherwise the conversion would
    silently reject as "Payout not found". The network stays unknown (asn None).
    """
    try:
        return API().query(ip)
    except IpstackErr:
        logger.warning("ip-api lookup failed for %s; using GeoLite2 country", ip)
        return IpLookup(country_code=geoip.country_code(ip))


@_celery.task
def click(data):
    lookup = lookup_ip(data["ip"])

    try:
        user = get_user_model().objects.get(pk=data['pid'])
    except get_user_model().DoesNotExist:
        msg = f"affiliate {data['pid']} not found"
        print(msg)
        return msg

    click = Click()
    click.id = data['click_id']
    click.offer_id = data['offer_id']
    click.brand_id = resolve_click_brand(data['offer_id'], data.get('request_brand_id'))
    click.affiliate_id = data['pid']
    click.affiliate_manager = user.profile.manager
    click.sub1 = data['sub1']
    click.sub2 = data['sub2']
    click.sub3 = data['sub3']
    click.sub4 = data['sub4']
    click.sub5 = data['sub5']
    click.revenue = 0
    click.payout = 0
    click.ip = data['ip']
    click.country = lookup.country_code
    click.asn = lookup.asn
    click.isp = lookup.isp
    click.is_mobile = lookup.mobile
    click.ua = data['ua']
    click.save()

    # Chain fraud scoring after click is persisted
    from fraud.tasks import score_click_fraud
    score_click_fraud.delay(str(click.id))

    return f"Click created: {click.id}"

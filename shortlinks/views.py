from django.db.models import F
from django.http import Http404
from django.utils import timezone

from shortlinks.models import ShortLink
from tracker.views import track_click


def go(request, slug):
    """Resolve a short link and record a click exactly as /click would.

    Extra ?sub1..sub5 on the short URL override the stored values, so one link
    can still carry per-placement tracking.
    """
    link = (
        ShortLink.objects
        .select_related('offer', 'affiliate__profile')
        .filter(slug=slug.lower(), is_active=True)
        .first()
    )
    if link is None or not _still_allowed(link):
        raise Http404

    subs = link.subs()
    for key in subs:
        if request.GET.get(key):
            subs[key] = request.GET[key]

    ShortLink.objects.filter(pk=link.pk).update(clicks=F('clicks') + 1, last_click_at=timezone.now())
    return track_click(request, link.offer_id, link.affiliate_id, subs, fb_id=request.GET.get('fb_id', ''))


def _still_allowed(link):
    """The affiliate may still send to this offer (same rule as the offers page)."""
    from affiliate_ui.gates import _is_approved
    from affiliate_ui.views.general_views import offers_for_affiliate

    return (
        _is_approved(link.affiliate)
        and offers_for_affiliate(link.affiliate).filter(pk=link.offer_id).exists()
    )

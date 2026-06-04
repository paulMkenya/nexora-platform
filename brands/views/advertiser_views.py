"""Operator views for advertiser approval at /admin/advertisers/.

The advertiser counterpart to the affiliate management console
(``affiliate_ui.views.admin_views``). Role hierarchy, enforced server-side:

  * PLATFORM OWNER (superuser) — every advertiser across every brand.
  * BRAND ADMIN (NETWORK_ADMIN) — only their own brand's advertisers; may
    approve/reject/suspend.
  * AFFILIATE MANAGER — blocked entirely (``brand_admin_required``).

Scoping is enforced at the OBJECT level: every action looks the advertiser up
*through* ``_scoped_advertisers``, so a brand-A admin reaching a brand-B
advertiser by direct ID gets a 404 — not just an empty list.
"""
import logging

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.email import send_brand_mail
from brands.permissions import brand_admin_required
from brands.scoping import scope_brand, sees_all_brands
from offer.models import Advertiser

logger = logging.getLogger(__name__)


def _scoped_advertisers(request):
    """Advertiser queryset visible to the current operator's role."""
    qs = Advertiser.objects.select_related('user', 'brand').order_by('-id')
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _get_advertiser_or_404(request, pk):
    """Fetch an advertiser, 404 if outside the operator's brand scope."""
    return get_object_or_404(_scoped_advertisers(request), pk=pk)


def _notify_approved(request, advertiser):
    brand = getattr(request, 'brand', None)
    brand_name = brand.name if brand else 'Nexora'
    host = (brand.primary_domain if brand else None) or request.META.get('HTTP_HOST', 'localhost')
    to = advertiser.user.email if advertiser.user else advertiser.email
    if not to:
        return
    name = (advertiser.user.first_name if advertiser.user else '') or advertiser.company
    subject = f'Your {brand_name} advertiser account has been approved!'
    body = (
        f'Hi {name},\n\n'
        f'Great news — your advertiser account on {brand_name} has been approved.\n'
        f'You can now create offers and fund your wallet.\n\n'
        f'Log in at: https://{host}/advertiser/login/\n'
    )
    try:
        send_brand_mail(brand, subject, body, [to], fail_silently=False)
    except Exception:
        logger.warning('SMTP not configured — approved notification for %s', to)


@brand_admin_required
def advertiser_list(request):
    qs = _scoped_advertisers(request)

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(advertiser_status=status_filter)

    return render(request, 'admin_shared/advertisers.html', {
        'active': 'advertisers',
        'advertisers': qs,
        'status_filter': status_filter,
        'status_choices': Advertiser.AdvertiserStatus.choices,
        'sees_all_brands': sees_all_brands(request.user),
        'APPROVED': Advertiser.AdvertiserStatus.APPROVED,
        'PENDING': Advertiser.AdvertiserStatus.PENDING,
        'REJECTED': Advertiser.AdvertiserStatus.REJECTED,
        'SUSPENDED': Advertiser.AdvertiserStatus.SUSPENDED,
    })


def _set_status(request, pk, status):
    advertiser = _get_advertiser_or_404(request, pk)
    advertiser.advertiser_status = status
    advertiser.save(update_fields=['advertiser_status'])
    return advertiser


@brand_admin_required
@require_POST
def advertiser_approve(request, pk):
    advertiser = _set_status(request, pk, Advertiser.AdvertiserStatus.APPROVED)
    _notify_approved(request, advertiser)
    return redirect('/admin/advertisers/')


@brand_admin_required
@require_POST
def advertiser_reject(request, pk):
    _set_status(request, pk, Advertiser.AdvertiserStatus.REJECTED)
    return redirect('/admin/advertisers/')


@brand_admin_required
@require_POST
def advertiser_suspend(request, pk):
    _set_status(request, pk, Advertiser.AdvertiserStatus.SUSPENDED)
    return redirect('/admin/advertisers/')

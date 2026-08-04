"""Lifecycle (archive) write-side: the Archived home + archive / restore /
hard-delete actions for affiliates, advertisers and brands.

This is the counterpart to the read-side exclusions wired across the active
consoles (see ``brands.archival`` and the ``is_archived=False`` filters in the
affiliate/advertiser/brand lists, gates and middleware). The active lists carry
an **Archive** button; everything reversible or destructive lives here, behind
``/admin/archived/``.

Role hierarchy (enforced server-side, never trusting the UI):

  * PLATFORM OWNER (superuser) — every entity across every brand; the only role
    that may archive / restore / delete **brands**.
  * BRAND ADMIN (NETWORK_ADMIN) — only their own brand's affiliates and
    advertisers. Object-level scoped: a cross-brand pk is a 404, not an empty
    action.
  * AFFILIATE MANAGER — blocked entirely (``brand_admin_required``).

Two guarantees:

  * **Archive is always allowed and always reversible** — it only flips the
    soft-delete flag (``brands.archival.Archivable``); financial history is never
    touched.
  * **Hard delete is guarded** — permitted only for a *genuinely empty* entity
    (no financial records), decided exclusively by ``brands.lifecycle``. Brands
    additionally can never be the default brand, and their external NPM/DNS
    cleanup is surfaced as instructions, never performed automatically.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.lifecycle import (
    advertiser_financials,
    affiliate_financials,
    brand_financials,
)
from brands.models import Brand
from brands.permissions import brand_admin_required, platform_owner_required
from brands.scoping import scope_brand, sees_all_brands
from offer.models import Advertiser
from user_profile.models import Profile

logger = logging.getLogger(__name__)

ARCHIVED_HOME = '/admin/archived/'


# ── object-level scoping (includes archived rows, unlike the active consoles) ──

def _affiliate_scope(request):
    """Affiliate profiles the operator may act on — archived ones included.

    Brand-scoped to the operator's own brand (superuser sees all). Restore and
    hard-delete look the object up *through* this queryset, so a brand-A admin
    reaching a brand-B (or out-of-scope) affiliate by direct pk gets a 404.
    """
    qs = Profile.objects.select_related('user', 'brand').filter(
        role=Profile.Role.AFFILIATE)
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _advertiser_scope(request):
    """Advertisers the operator may act on — archived ones included."""
    qs = Advertiser.objects.select_related('user', 'brand')
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _get_affiliate(request, pk):
    return get_object_or_404(_affiliate_scope(request), pk=pk)


def _get_advertiser(request, pk):
    return get_object_or_404(_advertiser_scope(request), pk=pk)


# ── Archived home ─────────────────────────────────────────────────────────────

@brand_admin_required
def archived_home(request):
    """The single surface that lists archived rows and offers Restore /
    (conditional) Hard-delete.

    Scope: a brand admin sees only their own brand's archived affiliates and
    advertisers; the platform owner sees every brand's, plus the archived-brands
    section (brand lifecycle is owner-only).
    """
    owner = sees_all_brands(request.user)

    affiliates = [
        {'profile': p, 'fin': affiliate_financials(p)}
        for p in _affiliate_scope(request).filter(is_archived=True).order_by('-archived_at')
    ]
    advertisers = [
        {'advertiser': a, 'fin': advertiser_financials(a)}
        for a in _advertiser_scope(request).filter(is_archived=True).order_by('-archived_at')
    ]
    brands = []
    if owner:
        brands = [
            {'brand': b, 'fin': brand_financials(b)}
            for b in Brand.objects.filter(is_archived=True).order_by('-archived_at')
        ]

    return render(request, 'admin_shared/archived.html', {
        'active': 'archived',
        'shell_role': 'admin',
        'page_title': 'Archived',
        'affiliates': affiliates,
        'advertisers': advertisers,
        'brands': brands,
        'show_brands': owner,
    })


# ── affiliate lifecycle ───────────────────────────────────────────────────────

@brand_admin_required
@require_POST
def affiliate_archive(request, pk):
    profile = _get_affiliate(request, pk)
    profile.archive(by=request.user)
    messages.success(request, f'Affiliate "{profile.user.username}" archived.')
    return redirect('/admin/affiliates/')


@brand_admin_required
@require_POST
def affiliate_restore(request, pk):
    profile = _get_affiliate(request, pk)
    profile.restore()
    messages.success(request, f'Affiliate "{profile.user.username}" restored.')
    return redirect(ARCHIVED_HOME)


@brand_admin_required
@require_POST
def affiliate_delete(request, pk):
    """Permanently delete an archived, financially-empty affiliate.

    Deletes the auth user, which cascades the profile. Blocked (with a clear
    reason) the moment the affiliate carries any financial record.
    """
    profile = _get_affiliate(request, pk)
    fin = affiliate_financials(profile)
    if not fin['can_hard_delete']:
        messages.error(
            request,
            f'Cannot delete "{profile.user.username}": {fin["block_reason"]}.')
        return redirect(ARCHIVED_HOME)
    username = profile.user.username
    profile.user.delete()  # OneToOne CASCADE removes the profile too
    messages.success(request, f'Affiliate "{username}" permanently deleted.')
    return redirect(ARCHIVED_HOME)


# ── advertiser lifecycle ──────────────────────────────────────────────────────

@brand_admin_required
@require_POST
def advertiser_archive(request, pk):
    advertiser = _get_advertiser(request, pk)
    advertiser.archive(by=request.user)
    messages.success(request, f'Advertiser "{advertiser.company}" archived.')
    return redirect('/admin/advertisers/')


@brand_admin_required
@require_POST
def advertiser_restore(request, pk):
    advertiser = _get_advertiser(request, pk)
    advertiser.restore()
    messages.success(request, f'Advertiser "{advertiser.company}" restored.')
    return redirect(ARCHIVED_HOME)


@brand_admin_required
@require_POST
def advertiser_delete(request, pk):
    """Permanently delete an archived, financially-empty advertiser.

    Offers (if any) are orphaned via SET_NULL, never destroyed. Blocked the
    moment the advertiser carries any conversion or wallet activity.
    """
    advertiser = _get_advertiser(request, pk)
    fin = advertiser_financials(advertiser)
    if not fin['can_hard_delete']:
        messages.error(
            request,
            f'Cannot delete "{advertiser.company}": {fin["block_reason"]}.')
        return redirect(ARCHIVED_HOME)
    name = advertiser.company
    user = advertiser.user
    advertiser.delete()
    if user is not None:
        user.delete()
    messages.success(request, f'Advertiser "{name}" permanently deleted.')
    return redirect(ARCHIVED_HOME)


# ── brand lifecycle (platform owner only) ─────────────────────────────────────

@platform_owner_required
@require_POST
def brand_archive(request, pk):
    """Archive (disable) a brand. The default brand is protected — disabling it
    would leave host resolution with no active fallback."""
    brand = get_object_or_404(Brand, pk=pk)
    if brand.is_default:
        messages.error(request, 'The default brand cannot be archived.')
        return redirect('brands_admin:brand_list')
    brand.archive(by=request.user)
    messages.success(request, f'Brand "{brand.name}" archived — its domains now '
                              f'fall back to the default brand.')
    return redirect('brands_admin:brand_list')


@platform_owner_required
@require_POST
def brand_restore(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    brand.restore()
    messages.success(request, f'Brand "{brand.name}" restored.')
    return redirect(ARCHIVED_HOME)

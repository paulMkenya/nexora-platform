"""Gating helpers for PENDING / unverified advertisers.

Mirror of ``affiliate_ui.gates``. A PENDING or unverified advertiser can log in
and reach their dashboard (with a pending banner) but is blocked from creating
offers and funding a wallet until status=APPROVED AND email_verified=True. The
gate runs on the view — the UI banner is only a hint.

Usage:
    @require_active_advertiser
    def my_view(request): ...
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseForbidden
from django.shortcuts import render

from offer.models import Advertiser
from user_profile.models import Profile

_BLOCKED_TEMPLATE = 'advertiser_ui/gated.html'


def is_active_advertiser(user):
    """True for an ADVERTISER whose record is APPROVED and email-verified."""
    try:
        if user.profile.role != Profile.Role.ADVERTISER:
            return False
        adv = user.advertiser_profile
    except (Profile.DoesNotExist, ObjectDoesNotExist, AttributeError):
        return False
    return (
        adv.advertiser_status == Advertiser.AdvertiserStatus.APPROVED
        and adv.email_verified
    )


def require_active_advertiser(view_func):
    """Block PENDING/unverified advertisers with a 403 page."""
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_active_advertiser(request.user):
            return HttpResponseForbidden(
                render(request, _BLOCKED_TEMPLATE).content
            )
        return view_func(request, *args, **kwargs)
    return _wrapped

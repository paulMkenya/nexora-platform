"""
Gating helpers for PENDING / unverified affiliates.

Usage (function-based views):
    @require_approved_affiliate
    def my_view(request): ...

Usage (class-based views):
    class MyView(ApprovedAffiliateMixin, View): ...

A PENDING or unverified affiliate can reach the dashboard but is blocked from
offer details, tracking-link generation, payouts, and smart-link management.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator

from user_profile.models import Profile

_BLOCKED_TEMPLATE = 'affiliate_ui/gated.html'


def _is_approved(user):
    try:
        p = user.profile
        return (
            p.role == Profile.Role.AFFILIATE
            and p.affiliate_status == Profile.AffiliateStatus.APPROVED
            and p.email_verified
            and not p.is_archived
        )
    except Exception:
        return False


def require_approved_affiliate(view_func):
    """Blocks PENDING/unverified affiliates with a 403 page."""
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _is_approved(request.user):
            return HttpResponseForbidden(
                render(request, _BLOCKED_TEMPLATE).content
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


class ApprovedAffiliateMixin:
    @method_decorator(require_approved_affiliate)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

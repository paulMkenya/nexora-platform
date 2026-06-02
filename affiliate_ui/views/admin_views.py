"""Operator views for affiliate management at /admin/affiliates/.

Role hierarchy enforced here (server-side, never trusting the UI):

  * PLATFORM OWNER (superuser) — every affiliate across every brand.
  * BRAND ADMIN (NETWORK_ADMIN) — only their own brand's affiliates; may
    approve/reject/suspend and assign/reassign/unassign a manager.
  * AFFILIATE MANAGER — only the affiliates assigned to them; may view detail
    and payouts but may NOT approve/reject/suspend or assign managers.
"""
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.permissions import affiliate_console_required, brand_admin_required
from brands.scoping import (
    is_affiliate_manager,
    is_brand_admin,
    operator_brand,
    scope_brand,
    sees_all_brands,
)
from user_profile.models import Profile

logger = logging.getLogger(__name__)

User = get_user_model()


def _scoped_affiliates(request):
    """Affiliate-profile queryset visible to the current operator's role."""
    qs = Profile.objects.select_related('user', 'manager', 'brand').filter(
        role=Profile.Role.AFFILIATE
    )
    if sees_all_brands(request.user):
        return qs
    if is_affiliate_manager(request.user):
        # A manager only ever sees the affiliates assigned to them, and only
        # within their own brand.
        return qs.filter(manager=request.user, brand=scope_brand(request))
    # Brand admin: their whole brand.
    return qs.filter(brand=scope_brand(request))


def _get_affiliate_or_404(request, pk):
    """Fetch an affiliate profile, 404 if outside the operator's scope.

    This is what makes "cannot reach brand B / unassigned affiliate by direct
    ID" true: the object is looked up *through* the role-scoped queryset.
    """
    return get_object_or_404(_scoped_affiliates(request), pk=pk)


def _brand_managers(brand):
    """Affiliate-manager users belonging to a brand (for the assign dropdown)."""
    if brand is None:
        return User.objects.none()
    return User.objects.filter(
        profile__role=Profile.Role.AFFILIATE_MANAGER,
        profile__brand=brand,
    ).select_related('profile').order_by('username')


def _notify_approved(request, user):
    brand = getattr(request, 'brand', None)
    brand_name = brand.name if brand else 'Nexora'
    host = (brand.primary_domain if brand else None) or request.META.get('HTTP_HOST', 'localhost')
    subject = f'Your {brand_name} account has been approved!'
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Great news — your affiliate account on {brand_name} has been approved.\n\n'
        f'Log in at: https://{host}/partner/login/\n'
    )
    try:
        send_mail(subject, body, None, [user.email], fail_silently=False)
    except Exception:
        logger.warning('SMTP not configured — approved notification for %s', user.email)


@affiliate_console_required
def affiliate_list(request):
    qs = _scoped_affiliates(request)

    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(affiliate_status=status_filter)

    # Only brand admins / owners moderate and assign managers; managers get a
    # read-only slice of their own assignees.
    can_moderate = is_brand_admin(request.user) or sees_all_brands(request.user)
    managers = _brand_managers(operator_brand(request.user)) if can_moderate else User.objects.none()

    return render(request, 'affiliate_ui/admin_affiliates.html', {
        'profiles': qs,
        'status_filter': status_filter,
        'status_choices': Profile.AffiliateStatus.choices,
        'can_moderate': can_moderate,
        'is_manager_view': is_affiliate_manager(request.user),
        'managers': managers,
    })


@affiliate_console_required
def affiliate_detail(request, pk):
    """Affiliate detail + payout history, scoped to the operator's role."""
    from payouts.models import PayoutRequest

    profile = _get_affiliate_or_404(request, pk)
    payouts = (
        PayoutRequest.objects
        .filter(affiliate=profile.user)
        .order_by('-created_at')[:50]
    )
    can_moderate = is_brand_admin(request.user) or sees_all_brands(request.user)
    managers = _brand_managers(profile.brand) if can_moderate else User.objects.none()

    return render(request, 'affiliate_ui/admin_affiliate_detail.html', {
        'profile': profile,
        'payouts': payouts,
        'can_moderate': can_moderate,
        'managers': managers,
    })


def _set_status(request, pk, status):
    profile = _get_affiliate_or_404(request, pk)
    profile.affiliate_status = status
    profile.save(update_fields=['affiliate_status'])
    return profile


@brand_admin_required
@require_POST
def affiliate_approve(request, pk):
    profile = _set_status(request, pk, Profile.AffiliateStatus.APPROVED)
    _notify_approved(request, profile.user)
    return redirect('/admin/affiliates/')


@brand_admin_required
@require_POST
def affiliate_reject(request, pk):
    _set_status(request, pk, Profile.AffiliateStatus.REJECTED)
    return redirect('/admin/affiliates/')


@brand_admin_required
@require_POST
def affiliate_suspend(request, pk):
    _set_status(request, pk, Profile.AffiliateStatus.SUSPENDED)
    return redirect('/admin/affiliates/')


@brand_admin_required
@require_POST
def affiliate_assign_manager(request, pk):
    """Assign / reassign / unassign an affiliate's manager (brand admin only).

    The chosen manager must be an AFFILIATE_MANAGER in the *same brand* as the
    affiliate. An empty value unassigns. Validation is enforced here regardless
    of what the form offered.
    """
    profile = _get_affiliate_or_404(request, pk)
    manager_id = (request.POST.get('manager') or '').strip()

    if not manager_id:
        profile.manager = None
        profile.save(update_fields=['manager'])
        messages.success(request, f'Manager unassigned from {profile.user.username}.')
        return redirect(request.POST.get('next') or '/admin/affiliates/')

    manager = User.objects.filter(
        pk=manager_id,
        profile__role=Profile.Role.AFFILIATE_MANAGER,
        profile__brand=profile.brand,
    ).first()
    if manager is None:
        messages.error(request, 'Invalid manager: must be an affiliate manager in this brand.')
        return redirect(request.POST.get('next') or '/admin/affiliates/')

    profile.manager = manager
    profile.save(update_fields=['manager'])
    messages.success(request, f'{manager.username} assigned to {profile.user.username}.')
    return redirect(request.POST.get('next') or '/admin/affiliates/')

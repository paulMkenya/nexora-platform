"""Role-management console at /admin/roles/.

Two appointment flows, each guarded server-side:

  * PLATFORM OWNER (superuser) may appoint any user as a BRAND ADMIN for a
    chosen brand (role=NETWORK_ADMIN, Profile.brand set, is_staff=True, and
    is_superuser forced off).
  * BRAND ADMIN may appoint AFFILIATE MANAGERS *within their own brand only*
    (role=AFFILIATE_MANAGER, Profile.brand = their brand). A brand admin can
    never create a superuser, a brand admin, or a manager for another brand —
    the brand is taken from the actor, not the form.
"""
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import redirect, render

from brands.models import Brand
from brands.permissions import brand_admin_required, platform_owner_required
from brands.scoping import is_platform_owner, operator_brand, scope_brand, sees_all_brands
from user_profile.models import Profile

logger = logging.getLogger(__name__)
User = get_user_model()


def _scoped_managers(request):
    """Affiliate-manager profiles visible to the current operator — archived
    excluded, brand-confined (a superuser sees all).

    The single source of truth for "which managers this operator may see/act on",
    mirroring ``_scoped_affiliates`` / ``_scoped_advertisers``. Reused by the
    impersonation scope check so managers are impersonable strictly downward and
    within scope, with no parallel permission path.
    """
    qs = (
        Profile.objects
        .filter(role=Profile.Role.AFFILIATE_MANAGER, is_archived=False)
        .select_related('user', 'brand')
    )
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _find_user(identifier):
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    return (
        User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
        .select_related('profile')
        .first()
    )


@brand_admin_required
def roles_home(request):
    """Role console. Platform owner manages brand admins; brand admin manages
    its own affiliate managers."""
    owner = is_platform_owner(request.user)
    ctx = {'active': 'roles', 'is_platform_owner': owner}

    if owner:
        ctx['brands'] = Brand.objects.all()
        ctx['brand_admins'] = (
            Profile.objects.filter(role=Profile.Role.NETWORK_ADMIN)
            .select_related('user', 'brand')
            .order_by('brand__name', 'user__username')
        )
        ctx['managers'] = _scoped_managers(request).order_by('brand__name', 'user__username')
    else:
        brand = operator_brand(request.user)
        ctx['brand'] = brand
        ctx['managers'] = _scoped_managers(request).order_by('user__username')

    return render(request, 'brands/admin/roles.html', ctx)


@platform_owner_required
def appoint_brand_admin(request):
    """Platform-owner-only: make a user a BRAND ADMIN for a chosen brand."""
    if request.method != 'POST':
        return redirect('roles_admin:home')

    user = _find_user(request.POST.get('identifier'))
    brand = Brand.objects.filter(pk=request.POST.get('brand') or 0).first()

    if user is None:
        messages.error(request, 'No user found with that username or email.')
        return redirect('roles_admin:home')
    if brand is None:
        messages.error(request, 'Choose a valid brand.')
        return redirect('roles_admin:home')

    profile = user.profile
    profile.role = Profile.Role.NETWORK_ADMIN
    profile.brand = brand
    profile.save(update_fields=['role', 'brand'])
    # A brand admin operates the custom console (is_staff) but is never a
    # platform owner.
    if user.is_superuser or not user.is_staff:
        user.is_superuser = False
        user.is_staff = True
        user.save(update_fields=['is_superuser', 'is_staff'])

    messages.success(request, f'{user.username} is now a brand admin for {brand.name}.')
    return redirect('roles_admin:home')


@brand_admin_required
def appoint_manager(request):
    """Appoint an AFFILIATE MANAGER. Brand admins are confined to their own brand."""
    if request.method != 'POST':
        return redirect('roles_admin:home')

    user = _find_user(request.POST.get('identifier'))
    if user is None:
        messages.error(request, 'No user found with that username or email.')
        return redirect('roles_admin:home')

    # The brand is taken from the actor for brand admins; only the platform
    # owner may target an arbitrary brand.
    if is_platform_owner(request.user):
        brand = Brand.objects.filter(pk=request.POST.get('brand') or 0).first()
        if brand is None:
            messages.error(request, 'Choose a valid brand.')
            return redirect('roles_admin:home')
    else:
        brand = operator_brand(request.user)
        if brand is None:
            messages.error(request, 'Your account is not bound to a brand.')
            return redirect('roles_admin:home')

    profile = user.profile
    profile.role = Profile.Role.AFFILIATE_MANAGER
    profile.brand = brand
    profile.save(update_fields=['role', 'brand'])
    # Managers are scoped operators, never staff or superusers.
    if user.is_superuser or user.is_staff:
        user.is_superuser = False
        user.is_staff = False
        user.save(update_fields=['is_superuser', 'is_staff'])

    messages.success(request, f'{user.username} is now an affiliate manager for {brand.name}.')
    return redirect('roles_admin:home')

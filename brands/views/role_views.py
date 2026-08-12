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
    """Role console. Platform owner manages brand admins across every brand;
    a brand admin manages the admins and affiliate managers of its own."""
    owner = is_platform_owner(request.user)
    ctx = {
        'active': 'roles', 'is_platform_owner': owner,
        'shell_role': 'admin',
        'page_title': 'Roles & Admins',
    }

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
        # A brand admin runs its own tenant's admin roster: it may see and
        # appoint co-admins WITHIN its brand (never across brands, never a
        # platform owner). The brand is taken from the actor, so there is no
        # brand chooser to render — see appoint_brand_admin.
        ctx['brand_admins'] = (
            Profile.objects.filter(role=Profile.Role.NETWORK_ADMIN, brand=brand)
            .select_related('user', 'brand')
            .order_by('user__username')
        )
        ctx['managers'] = _scoped_managers(request).order_by('user__username')

    ctx['roster'] = {
        'brand_admins': ctx['brand_admins'].count(),
        'managers': ctx['managers'].count(),
        'brands': ctx['brands'].count() if owner else 1,
    }

    # The nearest thing to an audit trail this platform keeps. There is no
    # general admin-action log — impersonation is the one privileged action
    # that records itself — so this panel says exactly what it is rather than
    # implying a fuller history exists.
    from impersonation.models import ImpersonationLog

    recent = ImpersonationLog.objects.select_related('impersonator', 'target').order_by('-id')
    if not owner:
        recent = recent.filter(target__profile__brand=operator_brand(request.user))
    ctx['recent_impersonations'] = recent[:8]

    return render(request, 'brands/admin/roles.html', ctx)


@brand_admin_required
def appoint_brand_admin(request):
    """Make a user a BRAND ADMIN. A platform owner may target any brand; a
    brand admin may only appoint co-admins for its OWN brand — the brand comes
    from the actor, never from the form, exactly as in appoint_manager."""
    if request.method != 'POST':
        return redirect('roles_admin:home')

    user = _find_user(request.POST.get('identifier'))

    if is_platform_owner(request.user):
        brand = Brand.objects.filter(pk=request.POST.get('brand') or 0).first()
    else:
        brand = operator_brand(request.user)

    if user is None:
        messages.error(request, 'No user found with that username or email.')
        return redirect('roles_admin:home')
    if brand is None:
        messages.error(request, 'Choose a valid brand.')
        return redirect('roles_admin:home')
    # Only the platform owner may demote a platform owner. Without this a brand
    # admin could name a superuser as its co-admin and the is_superuser=False
    # below would strip the platform owner's own access.
    if user.is_superuser and not is_platform_owner(request.user):
        messages.error(request, f'{user.username} is a platform owner — only another platform owner may change that.')
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

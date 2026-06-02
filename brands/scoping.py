"""Helpers for brand-scoping operator (network-admin) views.

Network-wide models such as payouts and fraud signals were historically shown
across every brand. In a multi-tenant deployment that leaks one brand's data to
another brand's operator, so operator views must scope to the operator's brand.

The single rule, used by payouts, fraud, the operator dashboard and affiliate
management:

  * superuser (platform owner)        → sees ALL brands (no scoping).
  * NETWORK_ADMIN / AFFILIATE_MANAGER → confined to their *own* assigned brand
    (``Profile.brand``), independent of which host they happen to reach the
    console through. Binding to the operator's own brand — rather than the
    request host — is what stops a brand-A admin from seeing brand B by simply
    visiting brand B's domain.

Records with no brand link (e.g. a payout whose affiliate has no brand) fall
out of every brand-scoped query and are therefore visible to superusers only;
callers log their presence so they don't go unnoticed.
"""

from user_profile.models import Profile


def _profile(user):
    return getattr(user, 'profile', None)


def sees_all_brands(user) -> bool:
    """True only for platform-owner superusers, who are not brand-scoped."""
    return bool(user and user.is_superuser)


def operator_brand(user):
    """The single brand a non-superuser operator is *assigned* to.

    Returns ``None`` for superusers (meaning "all brands") and for users with no
    profile/brand.
    """
    if sees_all_brands(user):
        return None
    prof = _profile(user)
    return getattr(prof, 'brand', None)


def scope_brand(request):
    """The brand an operator's view results are confined to.

    A brand admin / manager is bound to their *assigned* brand
    (``operator_brand``) so the console can't be widened by visiting another
    brand's domain. A staff operator with no assigned brand falls back to the
    request's brand (the legacy host-based behaviour). Superusers get ``None``
    (all brands).
    """
    if sees_all_brands(request.user):
        return None
    return operator_brand(request.user) or getattr(request, 'brand', None)


def is_brand_admin(user) -> bool:
    """A NETWORK_ADMIN scoped to one brand (explicitly NOT a superuser)."""
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    prof = _profile(user)
    return bool(prof and prof.role == Profile.Role.NETWORK_ADMIN)


def is_affiliate_manager(user) -> bool:
    """An AFFILIATE_MANAGER scoped to one brand."""
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    prof = _profile(user)
    return bool(prof and prof.role == Profile.Role.AFFILIATE_MANAGER)


def is_platform_owner(user) -> bool:
    """The platform owner is exactly a superuser."""
    return bool(user and user.is_authenticated and user.is_superuser)

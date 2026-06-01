"""
Permission helpers for the reporting API.

Reporting endpoints expose brand-wide aggregate metrics, so they must not be
reachable by affiliates (or any other role). Only two principals may call them:

  * Network Admin / superuser — sees brand-wide aggregates for request.brand.
  * Advertiser               — sees ONLY their own offers' aggregates.

Brand scoping alone is NOT sufficient: every authenticated user on a brand's
domain shares the same request.brand, so an affiliate would otherwise read the
whole brand's clicks/conversions/revenue. The view layer pairs this permission
with an explicit offer_ids filter for advertisers (see reporting.views).
"""
from rest_framework.permissions import BasePermission

from user_profile.models import Profile


def is_network_admin(user) -> bool:
    """True for superusers and users with the NETWORK_ADMIN role."""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == Profile.Role.NETWORK_ADMIN


def get_advertiser(user):
    """Return the user's Advertiser profile, or None."""
    if not (user and user.is_authenticated):
        return None
    return getattr(user, 'advertiser_profile', None)


class IsAdvertiserOrNetworkAdmin(BasePermission):
    """Allow only advertisers and network admins to read reports."""

    message = 'Reporting is restricted to advertisers and network admins.'

    def has_permission(self, request, view):
        user = request.user
        return is_network_admin(user) or get_advertiser(user) is not None

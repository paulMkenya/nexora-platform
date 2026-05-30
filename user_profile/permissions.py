from rest_framework.permissions import BasePermission

from user_profile.models import Profile


class IsAdvertiser(BasePermission):
    """Allow access only to users with the ADVERTISER role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role == Profile.Role.ADVERTISER
        except Exception:
            return False

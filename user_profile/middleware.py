from django.conf import settings
from django.shortcuts import redirect

from user_profile.models import Profile


class RolePortalMiddleware:
    """
    Redirect authenticated users to their role-based portal.

    Handles two cases:
    1. Authenticated user visits the login page (GET) → immediate redirect.
    2. Successful login POST with no `next` param → override the default
       LOGIN_REDIRECT_URL with the role-based portal URL.
    """

    PORTAL_BY_ROLE = {
        Profile.Role.AFFILIATE: '/partner/',
        Profile.Role.ADVERTISER: '/advertiser/',
        Profile.Role.AFFILIATE_MANAGER: '/admin/',
        Profile.Role.NETWORK_ADMIN: '/admin/',
    }
    DEFAULT_PORTAL = '/partner/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        login_path = settings.LOGIN_URL.rstrip('/')
        request_path = request.path.rstrip('/')

        # Case 1: already authenticated user hits the login page.
        if request_path == login_path and request.user.is_authenticated:
            return redirect(self._portal_for(request.user))

        response = self.get_response(request)

        # Case 2: successful login POST with no explicit `next` parameter
        # redirected to the default LOGIN_REDIRECT_URL — override with portal.
        if (
            request.method == 'POST'
            and request_path == login_path
            and response.status_code in (301, 302)
            and request.user.is_authenticated
            and not request.GET.get('next')
            and response.get('Location') == settings.LOGIN_REDIRECT_URL
        ):
            return redirect(self._portal_for(request.user))

        return response

    def _portal_for(self, user):
        try:
            return self.PORTAL_BY_ROLE.get(user.profile.role, self.DEFAULT_PORTAL)
        except Exception:
            return self.DEFAULT_PORTAL

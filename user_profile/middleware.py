from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

from user_profile.models import Profile


class RolePortalMiddleware:
    """
    Route authenticated users to their role-based portal and keep the Django
    model admin reserved for the platform owner.

    Three responsibilities:
    1. Authenticated user visits the login page (GET) → redirect to their portal.
    2. Successful login POST with no `next` param → override the default
       LOGIN_REDIRECT_URL with the role-based portal URL.
    3. Lock down the Django *model admin* (``django.contrib.admin`` — the
       ``admin`` URL namespace):
         * On a non-platform (brand/tenant) host the model admin and even its
           login page are never served — the request is redirected to the
           brand's operator login, so Django branding never leaks onto a
           white-labelled domain.
         * On a platform host the model admin works, but an authenticated
           non-superuser is bounced to their operator portal with a message.
       The custom operator console (/admin/dashboard/, /admin/affiliates/, …)
       lives under the same /admin/ prefix but in its own URL namespaces, so it
       is untouched — only views in the ``admin`` namespace are intercepted.
    """

    PORTAL_BY_ROLE = {
        Profile.Role.AFFILIATE: '/partner/',
        Profile.Role.ADVERTISER: '/advertiser/',
        Profile.Role.AFFILIATE_MANAGER: '/admin/affiliates/',
        Profile.Role.NETWORK_ADMIN: '/admin/dashboard/',
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

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Gate the Django model admin by host (and, on platform hosts, by role).

        Runs in process_view (after MessageMiddleware has initialised
        ``request._messages``) so it can attach a user-facing message. Only views
        in the ``admin`` namespace are intercepted; the custom operator console
        under /admin/ uses other namespaces and is left alone.
        """
        match = request.resolver_match
        if match is None or match.app_name != 'admin':
            return None

        host = request.get_host().split(':')[0].lower()
        if host not in settings.PLATFORM_ADMIN_HOSTS:
            # Brand/tenant domain: the Django admin (and its login) must never be
            # shown — not even to superusers or anonymous visitors. Send them to
            # this brand's operator login instead.
            return redirect(settings.LOGIN_URL)

        # Platform host: the model admin is for the platform owner only. Bounce
        # an authenticated non-superuser to their console (leave logout alone).
        if (
            request.user.is_authenticated
            and not request.user.is_superuser
            and match.url_name != 'logout'
        ):
            messages.info(
                request,
                'The Django admin is reserved for the platform owner. '
                'Here is your operator console.',
            )
            return redirect(self._portal_for(request.user))
        return None

    def _portal_for(self, user):
        try:
            return self.PORTAL_BY_ROLE.get(user.profile.role, self.DEFAULT_PORTAL)
        except Exception:
            return self.DEFAULT_PORTAL

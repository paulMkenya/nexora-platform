from django.shortcuts import redirect, render

from user_profile.models import Profile

_ROLE_PORTAL = {
    Profile.Role.AFFILIATE: '/partner/',
    Profile.Role.ADVERTISER: '/advertiser/',
    Profile.Role.AFFILIATE_MANAGER: '/admin/',
    Profile.Role.NETWORK_ADMIN: '/admin/',
}


def landing(request):
    if request.user.is_authenticated:
        try:
            portal = _ROLE_PORTAL.get(request.user.profile.role, '/partner/')
        except Exception:
            portal = '/partner/'
        return redirect(portal)
    return render(request, 'website/landing.html')

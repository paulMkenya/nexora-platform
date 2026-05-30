from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from user_profile.models import Profile


def advertiser_required(view_func):
    """Require login and ADVERTISER role; raise 403 for other roles."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            if request.user.profile.role != Profile.Role.ADVERTISER:
                raise PermissionDenied
        except Profile.DoesNotExist:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper

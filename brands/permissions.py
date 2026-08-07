"""Authorization helpers for the per-brand admin hierarchy.

Role model (see docs/CAPABILITIES.md and brands.scoping):

  * PLATFORM OWNER  = ``is_superuser``. Full Django model admin, sees all brands.
  * BRAND ADMIN     = ``NETWORK_ADMIN`` whose ``Profile.brand`` is set; NOT a
    superuser. Full admin of that ONE brand — including its brand settings and
    appointing co-admins/managers inside it — and nothing outside it. Uses the
    custom operator console; blocked from the Django model admin, from every
    cross-tenant surface (the brand roster, creating/deleting/archiving a
    brand, the platform sales funnel), and from the platform-level fields on
    its own brand (slug, domains, is_default — see
    brands.views.admin_views._BRAND_ADMIN_EDITABLE_FIELDS).
  * AFFILIATE MGR   = ``AFFILIATE_MANAGER``; scoped to one brand and, within it,
    to the affiliates assigned to them.

Every gate fails closed: an unauthenticated user is sent to the login page
(302); an authenticated user without the role is refused (``PermissionDenied``
→ 403). UI hints are never trusted — these run on the view.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from brands.scoping import (
    is_affiliate_manager,
    is_brand_admin,
    is_platform_owner,
)


def brand_required(field='brand'):
    """Decorator: raise PermissionDenied if obj.brand != request.brand."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def assert_same_brand(request, obj):
    """Raise PermissionDenied if obj.brand differs from request.brand."""
    obj_brand = getattr(obj, 'brand_id', None)
    req_brand = getattr(request.brand, 'pk', None)
    if obj_brand is not None and req_brand is not None and obj_brand != req_brand:
        raise PermissionDenied


def _role_gate(predicate):
    """Build a decorator that allows the request only if ``predicate(user)``."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not predicate(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


# Platform owner only (superuser): brand CRUD, appointing brand admins.
platform_owner_required = _role_gate(is_platform_owner)

# Brand admin or platform owner: affiliate approve/reject/suspend, manager
# assignment, appointing managers within a brand.
brand_admin_required = _role_gate(
    lambda u: is_platform_owner(u) or is_brand_admin(u)
)

# The whole affiliate console (list + detail): brand admin, affiliate manager,
# or platform owner. Managers see a strictly narrowed slice (their assignees).
affiliate_console_required = _role_gate(
    lambda u: is_platform_owner(u) or is_brand_admin(u) or is_affiliate_manager(u)
)

"""Who may impersonate whom — built entirely on the EXISTING object-level scoping.

This module deliberately does **not** introduce a parallel permission path. A
target is impersonable iff it falls inside the very same brand-scoped querysets
that already 404 out-of-scope rows in the operator consoles:

  * affiliates  → ``affiliate_ui.views.admin_views._scoped_affiliates``
  * advertisers → ``brands.views.advertiser_views._scoped_advertisers``

Both of those already exclude archived rows (``is_archived=False``) and confine a
brand admin to their own brand (a superuser sees all). So "strictly downward,
within scope, never archived" is enforced by reusing them rather than re-deriving
the rule:

  * PLATFORM OWNER (superuser) → any affiliate/advertiser in any brand.
  * BRAND ADMIN (NETWORK_ADMIN) → only affiliates/advertisers in their own brand.
  * AFFILIATE MANAGER / everyone else → nobody (``actor_may_impersonate`` is False).

Because the only impersonable rows are non-staff affiliates/advertisers, brand
admins, the platform owner and (currently) affiliate managers are never
impersonable — a fail-closed superset of "no sideways / no upward". A superuser
target is rejected explicitly as a second guard. Re-run :func:`scoped_target` on
every request to re-validate live (see the middleware).
"""
from types import SimpleNamespace

from brands.scoping import is_brand_admin, is_platform_owner, operator_brand


def actor_may_impersonate(actor) -> bool:
    """Only the platform owner and brand admins may ever impersonate."""
    return bool(actor) and (is_platform_owner(actor) or is_brand_admin(actor))


def _actor_scope_request(actor):
    """A minimal request-like object so we can call the real console scoping
    helpers (which read ``request.user`` and fall back to ``request.brand``)."""
    return SimpleNamespace(user=actor, brand=operator_brand(actor))


def scoped_target(actor, target):
    """Return ``(kind, obj, brand)`` if *actor* may impersonate *target*, else None.

    ``kind`` is ``'affiliate'`` or ``'advertiser'``; ``obj`` is the Profile/
    Advertiser row; ``brand`` is its brand. Pure (no side effects) so it is safe
    to call on every request for live re-validation.
    """
    if not actor_may_impersonate(actor):
        return None
    if target is None or not getattr(target, 'is_authenticated', False):
        return None
    # Never upward (a superuser is never a target) and never self.
    if target.is_superuser or target.pk == actor.pk:
        return None
    # Deactivated accounts are not impersonable.
    if not target.is_active:
        return None

    req = _actor_scope_request(actor)

    # Reuse the exact object-level scoping the consoles use (archived excluded,
    # brand-confined). Imported lazily to avoid import cycles at app load.
    from affiliate_ui.views.admin_views import _scoped_affiliates
    from brands.views.advertiser_views import _scoped_advertisers

    prof = _scoped_affiliates(req).filter(user=target).first()
    if prof is not None:
        return ('affiliate', prof, prof.brand)

    adv = _scoped_advertisers(req).filter(user=target).first()
    if adv is not None:
        return ('advertiser', adv, adv.brand)

    return None

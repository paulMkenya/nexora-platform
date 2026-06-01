"""Helpers for brand-scoping operator (network-admin) views.

Network-wide models such as payouts and fraud signals were historically shown
across every brand. In a multi-tenant deployment that leaks one brand's data to
another brand's operator, so operator views must scope to ``request.brand``.

The single rule, used by payouts, fraud, and the operator dashboard:

  * superuser (platform owner)        → sees ALL brands (no scoping).
  * NETWORK_ADMIN / AFFILIATE_MANAGER → confined to request.brand.

Records with no brand link (e.g. a payout whose affiliate has no brand) fall
out of every brand-scoped query and are therefore visible to superusers only;
callers log their presence so they don't go unnoticed.
"""


def sees_all_brands(user) -> bool:
    """True only for platform-owner superusers, who are not brand-scoped."""
    return bool(user and user.is_superuser)

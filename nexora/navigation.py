"""Single source of truth for role-based navigation (currently: admin/operator).

Templates never hardcode links — they render whatever a context processor
resolved from here. Adding/moving a nav item means editing this file only;
no template touches a URL name directly.

``nav_for`` returns the *static* shape (labels, url names, icons, visibility
rules) with no request dependency, so it's trivially unit-testable.
``resolve_nav_for_request`` is the request-aware layer: it reverses URLs,
decides which item is active (prefix-matched via each item's ``match_extra``
view names, so a sub-page like "edit offer" keeps "Offers" highlighted), and
drops anything the current user can't see.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: Optional[str] = None  # None => always-disabled "SOON" item
    icon: str = 'dot'
    badge: Optional[str] = None
    # Additional view_names (namespace:name) that should also count as "this
    # item is active" — e.g. the affiliate detail/approve/reject sub-pages all
    # keep "Affiliates" highlighted in the sidebar.
    match_extra: Tuple[str, ...] = field(default_factory=tuple)
    owner_only: bool = False


@dataclass(frozen=True)
class NavGroup:
    label: Optional[str]
    items: Tuple[NavItem, ...]
    quiet: bool = False  # SYSTEM: rendered last, de-emphasized


def _admin_groups(*, is_platform_owner: bool) -> Tuple[NavGroup, ...]:
    roles_label = 'Roles & Admins' if is_platform_owner else 'Managers'
    return (
        NavGroup('Overview', (
            NavItem('Dashboard', 'admin_dashboard', icon='dashboard'),
        )),
        NavGroup('People', (
            NavItem('Affiliates', 'affiliate_admin:list', icon='affiliates', match_extra=(
                'affiliate_admin:detail', 'affiliate_admin:approve',
                'affiliate_admin:reject', 'affiliate_admin:suspend',
                'affiliate_admin:assign_manager',
            )),
            NavItem('Advertisers', 'advertisers_admin:list', icon='advertisers', match_extra=(
                'advertisers_admin:approve', 'advertisers_admin:reject', 'advertisers_admin:suspend',
            )),
            NavItem('Leads', 'leads_admin:lead_list', icon='leads', match_extra=(
                'leads_admin:lead_update_stage', 'leads_admin:lead_add_note',
            )),
            NavItem(roles_label, 'roles_admin:home', icon='roles', match_extra=(
                'roles_admin:appoint_brand_admin', 'roles_admin:appoint_manager',
            )),
        )),
        NavGroup('Campaigns', (
            NavItem('Offers', 'offers_admin:list', icon='offers', match_extra=(
                'offers_admin:create', 'offers_admin:edit', 'offers_admin:set_status',
            )),
            NavItem('Brands', 'brands_admin:brand_list', icon='brands', owner_only=True, match_extra=(
                'brands_admin:brand_create', 'brands_admin:brand_edit',
                'brands_admin:brand_delete', 'brands_admin:brand_setup',
            )),
        )),
        NavGroup('Finance', (
            NavItem('Payouts', 'payouts_admin:payout_list', icon='payouts', match_extra=(
                'payouts_admin:batch_list', 'payouts_admin:holds_list', 'payouts_admin:control_settings',
            )),
        )),
        NavGroup('Fraud', (
            NavItem('Fraud Review', 'fraud:dashboard', icon='fraud'),
        )),
        NavGroup('Growth', (
            NavItem('Sales Funnel', 'platform_leads_admin:pipeline', icon='funnel', owner_only=True, match_extra=(
                'platform_leads_admin:lead_detail', 'platform_leads_admin:update_stage',
                'platform_leads_admin:add_note', 'platform_leads_admin:mark_contacted',
                'platform_leads_admin:settings',
            )),
            NavItem('Email', 'brands_admin:email_settings', icon='email'),
        )),
        NavGroup('System', (
            NavItem('API Docs', 'swagger-ui', icon='api_docs'),
            NavItem('Nexora Admin', 'admin:index', icon='nexora_admin', owner_only=True),
            NavItem('Archived', 'archived_admin:home', icon='archived'),
            NavItem('Impersonation', 'impersonation:log', icon='impersonation'),
        ), quiet=True),
    )


_MANAGER_GROUPS = (
    NavGroup(None, (
        NavItem('My Affiliates', 'affiliate_admin:list', icon='affiliates'),
    )),
)


def nav_for(role: str, *, is_platform_owner: bool = False, is_affiliate_manager: bool = False):
    """The static nav shape for ``role``. No request/URL-reversal here."""
    if role != 'admin':
        return ()
    if is_affiliate_manager:
        return _MANAGER_GROUPS
    return _admin_groups(is_platform_owner=is_platform_owner)


def resolve_nav_for_request(request, role: str):
    """Request-aware: reverse URLs, mark the active item, drop hidden items."""
    from brands.scoping import is_affiliate_manager as _iam, is_platform_owner as _ipo

    user = getattr(request, 'user', None)
    owner = _ipo(user)
    manager = _iam(user)
    current_view = getattr(request.resolver_match, 'view_name', None) if request.resolver_match else None

    groups = nav_for(role, is_platform_owner=owner, is_affiliate_manager=manager)
    resolved = []
    for group in groups:
        items = []
        for item in group.items:
            if item.owner_only and not owner:
                continue
            href = None
            if item.url_name:
                try:
                    href = reverse(item.url_name)
                except NoReverseMatch:
                    href = None
            active_names = (item.url_name,) + item.match_extra if item.url_name else item.match_extra
            is_active = current_view in active_names
            items.append({
                'label': item.label, 'href': href, 'icon': item.icon,
                'badge': item.badge, 'is_active': is_active,
            })
        if items:
            resolved.append({'label': group.label, 'items': items, 'quiet': group.quiet})
    return resolved


def navigation_context(request):
    """Context processor — wires the admin nav into every template automatically.

    Registered in ``project/settings/base.py`` TEMPLATES/context_processors.
    Only resolves the admin nav today; a future ``role`` param can extend this
    once affiliate/advertiser move their configs into this same registry
    (Phase 3 step 3 of the go-live guide).
    """
    return {'admin_nav': resolve_nav_for_request(request, 'admin')}

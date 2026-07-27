"""Start / stop impersonation, and the server-side audit log view."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.permissions import brand_admin_required
from brands.scoping import operator_brand, sees_all_brands
from impersonation.models import ImpersonationLog
from impersonation.permissions import scoped_target
from impersonation.service import (
    SESSION_ACTOR,
    SESSION_TARGET,
    clear_session,
    client_ip,
    close_open_log,
    set_session,
    start_log,
)

User = get_user_model()

_PORTAL = {
    'affiliate': '/partner/dashboard/',
    'advertiser': '/advertiser/',
    'manager': '/admin/affiliates/',
}


@brand_admin_required
@require_POST
def impersonate_start(request, user_id):
    """Begin impersonating *user_id*.

    Gated by ``brand_admin_required`` (owner or brand admin; affiliate managers
    and everyone else get 403). The target is then resolved through the SAME
    object-level scoping the consoles use — out-of-scope / archived / upward
    targets 404. Nesting is refused.
    """
    # No nesting: an already-impersonated session cannot start another. (The
    # decorator also blocks this, since request.user would be the non-admin
    # target, but we fail explicitly for clarity.)
    if getattr(request, 'is_impersonating', False):
        raise PermissionDenied('Cannot start impersonation while impersonating.')

    target = get_object_or_404(User, pk=user_id)
    match = scoped_target(request.user, target)
    if match is None:
        raise Http404('User is not impersonable.')

    kind, _obj, brand = match
    set_session(request, request.user.pk, target.pk)
    start_log(request.user, target, brand, client_ip(request))
    return redirect(_PORTAL.get(kind, '/'))


@require_POST
def impersonate_stop(request):
    """Return to the actor's own account. Idempotent and always safe to call."""
    actor_id = request.session.get(SESSION_ACTOR)
    target_id = request.session.get(SESSION_TARGET)
    close_open_log(actor_id, target_id)
    clear_session(request)
    return redirect('/admin/dashboard/')


@brand_admin_required
def impersonation_log(request):
    """Audit view: platform owner sees every brand; a brand admin sees only
    their own brand's impersonations."""
    qs = (
        ImpersonationLog.objects
        .select_related('impersonator', 'target', 'brand')
        .order_by('-started_at')
    )
    if not sees_all_brands(request.user):
        qs = qs.filter(brand=operator_brand(request.user))

    return render(request, 'impersonation/log.html', {
        'active': 'impersonation',
        'logs': qs[:300],
        'shell_role': 'admin',
        'page_title': 'Impersonation',
    })

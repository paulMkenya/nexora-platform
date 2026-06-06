"""Session + audit-log primitives shared by the views and the middleware."""
from django.utils import timezone

from impersonation.models import ImpersonationLog

SESSION_TARGET = 'impersonate_target_id'
SESSION_ACTOR = 'impersonator_id'


def client_ip(request):
    """Best-effort client IP. Behind the NPM proxy the real client is the first
    entry of X-Forwarded-For; fall back to REMOTE_ADDR."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


def start_log(actor, target, brand, ip):
    return ImpersonationLog.objects.create(
        impersonator=actor, target=target, brand=brand, impersonator_ip=ip,
    )


def close_open_log(actor_id, target_id):
    """Stamp ``ended_at`` on the still-open log for this actor→target pair."""
    if not actor_id or not target_id:
        return
    log = (
        ImpersonationLog.objects
        .filter(impersonator_id=actor_id, target_id=target_id, ended_at__isnull=True)
        .order_by('-started_at')
        .first()
    )
    if log is not None:
        log.ended_at = timezone.now()
        log.save(update_fields=['ended_at'])


def set_session(request, actor_id, target_id):
    request.session[SESSION_ACTOR] = actor_id
    request.session[SESSION_TARGET] = target_id


def clear_session(request):
    request.session.pop(SESSION_TARGET, None)
    request.session.pop(SESSION_ACTOR, None)

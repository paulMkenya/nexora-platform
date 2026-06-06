"""Impersonation middleware.

Runs immediately after Django's AuthenticationMiddleware. The real authenticated
user (the *actor*) is never logged out — we only swap ``request.user`` to the
target for the duration of the request, so "Return to your account" needs no
re-login. On every request we re-validate the actor's permission to impersonate
this target; if anything changed (target archived / reassigned / deactivated,
actor's role/scope changed), impersonation ends safely and the actor is back in
their own session.

While impersonating, the actor acts with the TARGET's privileges: because the
target is always a non-staff affiliate/advertiser, owner-only surfaces (Django
model admin, role console, brand CRUD, the Archived home's destructive actions)
are unreachable by construction — their gates check ``request.user``, which is
now the target.

A persistent banner is injected into every HTML response so the state is
unmissable on every page, whatever template rendered it.
"""
import re

from django.middleware.csrf import get_token
from django.utils.html import escape

from impersonation.permissions import scoped_target
from impersonation.service import (
    SESSION_ACTOR,
    SESSION_TARGET,
    clear_session,
    close_open_log,
)

_BODY_RE = re.compile(rb'<body[^>]*>', re.IGNORECASE)


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_impersonating = False
        request.impersonator = None
        self._maybe_swap(request)

        response = self.get_response(request)

        if getattr(request, 'is_impersonating', False):
            response = self._inject_banner(request, response)
        return response

    # -- swap + live re-validation ------------------------------------------
    def _maybe_swap(self, request):
        target_id = request.session.get(SESSION_TARGET)
        if not target_id:
            return

        actor = request.user
        # Actor's auth session is gone / actor deactivated → end safely.
        if not getattr(actor, 'is_authenticated', False):
            close_open_log(request.session.get(SESSION_ACTOR), target_id)
            clear_session(request)
            return

        from django.contrib.auth import get_user_model
        target = (
            get_user_model().objects
            .filter(pk=target_id)
            .select_related('profile')
            .first()
        )

        # RE-VALIDATE on every request using the same scoping as start.
        if scoped_target(actor, target) is None:
            close_open_log(actor.pk, target_id)
            clear_session(request)
            return

        request.user = target
        request.impersonator = actor
        request.is_impersonating = True

    # -- persistent banner ---------------------------------------------------
    def _inject_banner(self, request, response):
        # Only touch real in-memory HTML bodies (skip streaming/CSV/redirects).
        if getattr(response, 'streaming', False):
            return response
        if 'text/html' not in response.get('Content-Type', ''):
            return response
        if not getattr(response, 'content', b''):
            return response

        target = request.user
        actor = request.impersonator
        name = escape(target.get_full_name() or target.get_username())
        role = escape(self._role_label(target))
        actor_name = escape(actor.get_full_name() or actor.get_username())
        token = get_token(request)

        banner = (
            '<div style="position:sticky;top:0;left:0;right:0;z-index:2147483647;'
            'background:#b91c1c;color:#fff;font:600 14px system-ui,-apple-system,'
            'Segoe UI,Roboto,Arial,sans-serif;padding:10px 16px;display:flex;'
            'align-items:center;gap:12px;box-shadow:0 2px 6px rgba(0,0,0,.3);">'
            f'<span>⚠️ You are viewing as <strong>{name}</strong> ({role}) '
            f'— impersonated by {actor_name}. Money actions are disabled.</span>'
            '<form method="post" action="/admin/impersonate/stop/" '
            'style="margin:0 0 0 auto;display:inline;">'
            f'<input type="hidden" name="csrfmiddlewaretoken" value="{token}">'
            '<button type="submit" style="background:#fff;color:#b91c1c;border:0;'
            'border-radius:6px;padding:6px 12px;font-weight:700;cursor:pointer;">'
            'Return to your account</button></form></div>'
        ).encode('utf-8')

        content = response.content
        m = _BODY_RE.search(content)
        if m:
            idx = m.end()
            content = content[:idx] + banner + content[idx:]
        else:
            content = banner + content
        response.content = content
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response

    @staticmethod
    def _role_label(user):
        prof = getattr(user, 'profile', None)
        if prof is not None:
            try:
                return prof.get_role_display()
            except Exception:
                pass
        return 'user'

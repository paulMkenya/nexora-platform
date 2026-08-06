"""Marks a request whose session was created by autologin.

Mirrors ImpersonationMiddleware's contract deliberately: a single boolean on
the request that the shared sensitive-action gate reads, so a third restricted
session type later has an obvious place to slot in.

While the feature is disabled the attribute is not attached at all — not set to
False, not present. "Off" means the middleware is inert, so nothing downstream
can accidentally branch on a flag that only exists because the code is loaded.
"""
from . import config
from .views import SESSION_FLAG, SESSION_SCOPE


class AutologinSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if config.is_enabled():
            request.is_autologin_session = bool(request.session.get(SESSION_FLAG))
            request.autologin_scope = request.session.get(SESSION_SCOPE) or ''
        return self.get_response(request)

"""The money-movement guard used while impersonating.

WRITE ALLOWED, MONEY BLOCKED: a view wrapped with this still works normally for
the real owner of the session, but is refused server-side whenever the request is
an impersonated one — regardless of the target's own privileges. This is the
hard block behind every money path (payout request/methods/settings, operator
approve/mark-paid/dispatch).
"""
from functools import wraps

from django.http import HttpResponseForbidden


def block_when_impersonating(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request, 'is_impersonating', False):
            return HttpResponseForbidden(
                'This action is disabled during impersonation. '
                'Return to your own account to move money.'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped

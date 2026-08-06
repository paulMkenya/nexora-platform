"""The sensitive-action guard for sessions that are not a full, first-party login.

WRITE ALLOWED, MONEY BLOCKED: a view wrapped with this still works normally for
the real owner of a normally-authenticated session, but is refused server-side
whenever the request rides a RESTRICTED session — regardless of the acting
user's own privileges. This is the hard block behind every money and credential
path (payout request/methods/settings, operator approve/mark-paid/dispatch, API
key issuance, postback configuration).

Two restricted session types exist today:

  * impersonation — an operator acting as another user
    (impersonation.middleware.ImpersonationMiddleware)
  * autologin/SSO — a session minted from a signed bearer link
    (sso.middleware.AutologinSessionMiddleware)

`block_when_not_fully_authed` is the CANONICAL name because it states the
actual rule. `block_when_impersonating` remains as a deprecated alias so the
existing call sites keep working, but do not reach for it in new code: reading
"impersonating" invites the next person to assume impersonation is the whole
rule and to reason wrongly about whether a sensitive endpoint is covered.

Adding a third restricted session type means adding one entry to
`_RESTRICTIONS` — every already-decorated endpoint is then covered, and
leadgen/tests + impersonation/tests enumerate the protected set so a NEW
sensitive endpoint that forgets the decorator fails CI rather than shipping.
"""
from functools import wraps

from django.http import HttpResponseForbidden

# (request attribute, refusal message). Order is only cosmetic — the first
# matching restriction wins and explains itself.
_RESTRICTIONS = (
    (
        'is_impersonating',
        'This action is disabled during impersonation. '
        'Return to your own account to move money.',
    ),
    (
        'is_autologin_session',
        'This action is disabled for an autologin session. '
        'Sign in with your password to change payout, key or postback settings.',
    ),
)


def block_when_not_fully_authed(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        for attr, message in _RESTRICTIONS:
            if getattr(request, attr, False):
                return HttpResponseForbidden(message)
        return view_func(request, *args, **kwargs)
    return _wrapped


# Deprecated alias — kept so the ~19 existing call sites need no edit. New code
# should use block_when_not_fully_authed.
block_when_impersonating = block_when_not_fully_authed

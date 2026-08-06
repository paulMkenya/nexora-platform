"""The autologin redemption endpoint.

Hardening on the redirect is not decoration. A URL that logs someone in leaks
through the Referer header of the very next page load, through browser history,
through any proxy that logs URLs, and through a search crawler that finds it in
a shared inbox. So the redirect sets no-referrer, forbids caching, and asks not
to be indexed.

The token arrives in the query string because a browser following a link can
only carry it there — but it is single-use and it dies within ~120 seconds, and
the response strips the referrer so the next hop never sees it.
"""
import logging

from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import config
from .service import AutologinError, redeem_token

logger = logging.getLogger(__name__)

SESSION_FLAG = 'sso_autologin_session'
SESSION_SCOPE = 'sso_autologin_scope'

LANDING_BY_SCOPE = {
    'dashboard': '/partner/dashboard/',
}


def _harden(response):
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@require_GET
@never_cache
def redeem(request):
    """GET /sso/autologin/?token=... -> 302 into the bound landing scope.

    404 (never 403) on every failure: a 403 confirms the feature exists and
    that a token was recognisably wrong, which is free information to someone
    probing. The audit row records the real reason.
    """
    if not config.is_enabled():
        raise Http404

    token = request.GET.get('token') or ''
    if not token:
        raise Http404

    try:
        user, scope = redeem_token(token, request)
    except (AutologinError, config.AutologinDisabled):
        raise Http404

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    # Mark the session so the sensitive-action gate can refuse it. Set AFTER
    # login(), which cycles the session key and would otherwise drop the flag.
    request.session[SESSION_FLAG] = True
    request.session[SESSION_SCOPE] = scope

    landing = LANDING_BY_SCOPE.get(scope, LANDING_BY_SCOPE['dashboard'])
    return _harden(redirect(landing))

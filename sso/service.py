"""Issue and redeem Track B autologin tokens.

Design notes worth keeping in view when changing this:

* The token is signed, NOT encrypted (``django.core.signing`` — HMAC-SHA256,
  the framework's own utility, no new dependency). Anyone holding the token can
  read the payload, so the payload carries only what it must: the bound user
  id, the landing scope, a nonce, and an issued-at. No email, no name, no brand
  detail, nothing else.

* Expiry is checked twice, deliberately. ``signing.loads(max_age=...)`` catches
  a token that is too OLD. It does not catch one that is FUTURE-dated: age goes
  negative and the comparison passes. A signer with a skewed clock (or a second
  host sharing SECRET_KEY) could therefore mint something that outlives its TTL,
  so we carry our own ``iat`` and reject anything dated beyond a small
  tolerance.

* Everything fails CLOSED. If Redis — which backs both the rate limiter and the
  pre-check on nonce burning — is unreachable, issuance and redemption raise
  rather than falling back to an in-memory or no-op path. An unenforceable
  single-use guarantee is worse than an outage: it turns a one-shot credential
  into a replayable one, silently.
"""
import hashlib
import logging
import secrets
from datetime import timedelta

from django.core import signing
from django.core.cache import cache
from django.utils import timezone

from . import config
from .models import AutologinAttempt, AutologinToken

logger = logging.getLogger(__name__)


class AutologinError(Exception):
    """Base for every redemption failure, carrying the audited outcome."""

    outcome = AutologinAttempt.OUTCOME_TAMPERED

    def __init__(self, message=None):
        super().__init__(message or self.outcome)


class TokenExpired(AutologinError):
    outcome = AutologinAttempt.OUTCOME_EXPIRED


class TokenAlreadyUsed(AutologinError):
    outcome = AutologinAttempt.OUTCOME_ALREADY_USED


class TokenTampered(AutologinError):
    outcome = AutologinAttempt.OUTCOME_TAMPERED


class TokenFutureDated(AutologinError):
    outcome = AutologinAttempt.OUTCOME_FUTURE_DATED


class TokenUnknown(AutologinError):
    outcome = AutologinAttempt.OUTCOME_UNKNOWN_NONCE


class TokenUserUnusable(AutologinError):
    outcome = AutologinAttempt.OUTCOME_USER_UNUSABLE


class RateLimited(AutologinError):
    outcome = AutologinAttempt.OUTCOME_RATE_LIMITED


class StoreUnavailable(AutologinError):
    outcome = AutologinAttempt.OUTCOME_STORE_UNAVAILABLE


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request):
    """Best-effort client IP for the audit trail.

    NOTE: this takes the leftmost X-Forwarded-For entry, which is
    attacker-supplied. That is acceptable HERE because this value is only ever
    written to an audit row and a rate-limit key — it is never an authorisation
    input. Do not copy this into anything that grants access; see the parked
    IP-allowlist work for why the leftmost entry cannot be trusted.
    """
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        return xff.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def _user_agent(request):
    return (request.META.get('HTTP_USER_AGENT') or '')[:300]


def _bump_rate(key: str, limit: int):
    """Fail-closed fixed-window counter. Any cache error raises."""
    try:
        added = cache.add(key, 1, timeout=3600)
        count = 1 if added else cache.incr(key)
    except Exception as exc:  # Redis down / misconfigured
        logger.error('sso.autologin store unavailable on %s: %s', key, exc)
        raise StoreUnavailable('Rate/nonce store unavailable') from exc
    if count > limit:
        raise RateLimited(f'{key} exceeded {limit}/hour')


def _record(outcome, *, request, user=None, token_obj=None, hashed=''):
    """Write the audit row. Never raises into the caller's failure path."""
    try:
        AutologinAttempt.objects.create(
            user=user, token=token_obj, token_hash=hashed, outcome=outcome,
            ip=client_ip(request), user_agent=_user_agent(request),
        )
    except Exception:
        logger.exception('sso.autologin could not write audit row (outcome=%s)', outcome)
    logger.info(
        'sso.autologin outcome=%s user=%s ip=%s',
        outcome, getattr(user, 'pk', None), client_ip(request),
    )


def issue_token(user, *, scope='dashboard', request=None):
    """Mint a single-use autologin token for `user`.

    Raises AutologinDisabled while the feature is off — no code path may mint
    one, including management commands, the admin and test helpers.
    """
    if not config.is_enabled():
        raise config.AutologinDisabled(
            'SSO autologin is disabled; no token can be issued.')

    if request is not None:
        _bump_rate(f'sso:issue:{user.pk}', config.issue_rate_per_hour())
    else:
        # Still fail closed if the store is gone, even without a request.
        _bump_rate(f'sso:issue:{user.pk}', config.issue_rate_per_hour())

    now = timezone.now()
    nonce = secrets.token_urlsafe(32)
    payload = {
        'u': user.pk,          # bound user
        's': scope,            # bound landing scope
        'n': nonce,            # single-use handle
        'iat': int(now.timestamp()),
    }
    token = signing.dumps(payload, salt=config.SIGNING_SALT)

    AutologinToken.objects.create(
        nonce=nonce,
        token_hash=token_hash(token),
        user=user,
        scope=scope,
        issued_ip=client_ip(request) if request is not None else None,
        issued_user_agent=_user_agent(request) if request is not None else '',
        expires_at=now + timedelta(seconds=config.ttl_seconds()),
    )
    logger.info('sso.autologin issued user=%s scope=%s ttl=%ss',
                user.pk, scope, config.ttl_seconds())
    return token


def redeem_token(token: str, request):
    """Validate + burn `token`, returning the user it is bound to.

    Every failure path writes an AutologinAttempt before raising.
    """
    hashed = token_hash(token)

    if not config.is_enabled():
        _record(AutologinAttempt.OUTCOME_DISABLED, request=request, hashed=hashed)
        raise config.AutologinDisabled('SSO autologin is disabled.')

    try:
        _bump_rate(f'sso:redeem:{client_ip(request) or "unknown"}',
                   config.redeem_rate_per_hour())
    except AutologinError as exc:
        _record(exc.outcome, request=request, hashed=hashed)
        raise

    try:
        payload = signing.loads(
            token, salt=config.SIGNING_SALT, max_age=config.ttl_seconds())
    except signing.SignatureExpired:
        _record(AutologinAttempt.OUTCOME_EXPIRED, request=request, hashed=hashed)
        raise TokenExpired('Token expired')
    except signing.BadSignature:
        # Tampered or forged: we deliberately do NOT read the payload to find a
        # user id, because an unverified payload is attacker-controlled.
        _record(AutologinAttempt.OUTCOME_TAMPERED, request=request, hashed=hashed)
        raise TokenTampered('Bad signature')

    issued_at = int(payload.get('iat') or 0)
    skew = config.clock_skew_tolerance_seconds()
    if issued_at - int(timezone.now().timestamp()) > skew:
        _record(AutologinAttempt.OUTCOME_FUTURE_DATED, request=request, hashed=hashed)
        raise TokenFutureDated('Token issued in the future beyond tolerance')

    nonce = payload.get('n') or ''
    token_obj = AutologinToken.objects.filter(nonce=nonce).select_related('user').first()
    if token_obj is None:
        _record(AutologinAttempt.OUTCOME_UNKNOWN_NONCE, request=request, hashed=hashed)
        raise TokenUnknown('No issuance record for this token')

    # THE BURN. Atomic: Postgres serialises the row update, so exactly one of N
    # concurrent redemptions sees rowcount 1. Anything else is a replay.
    burned = (
        AutologinToken.objects
        .filter(pk=token_obj.pk, redeemed_at__isnull=True)
        .update(
            redeemed_at=timezone.now(),
            redeemed_ip=client_ip(request),
            redeemed_user_agent=_user_agent(request),
        )
    )
    if burned != 1:
        _record(AutologinAttempt.OUTCOME_ALREADY_USED, request=request,
                user=token_obj.user, token_obj=token_obj, hashed=hashed)
        raise TokenAlreadyUsed('Token already redeemed')

    user = token_obj.user
    if user is None or not user.is_active:
        _record(AutologinAttempt.OUTCOME_USER_UNUSABLE, request=request,
                user=user, token_obj=token_obj, hashed=hashed)
        raise TokenUserUnusable('Bound user is missing or inactive')

    _record(AutologinAttempt.OUTCOME_REDEEMED, request=request,
            user=user, token_obj=token_obj, hashed=hashed)
    return user, token_obj.scope

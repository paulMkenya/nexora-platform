"""Track B autologin behaviour with the feature ENABLED.

The tests that matter most here are the ones about a token being used more than
once, or by the wrong person, or after it should have died — a single-use login
credential whose single-use property is untested is just a login credential.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from sso import config
from sso.models import AutologinAttempt, AutologinToken
from sso.service import (
    RateLimited,
    StoreUnavailable,
    TokenAlreadyUsed,
    TokenExpired,
    TokenFutureDated,
    TokenTampered,
    issue_token,
    redeem_token,
    token_hash,
)
from sso.views import SESSION_FLAG

User = get_user_model()

@pytest.fixture(autouse=True)
def _feature_on(settings):
    settings.SSO_AUTOLOGIN_ENABLED = True


@pytest.fixture
def user(db):
    return User.objects.create_user(username='sso_on', password='pass', is_active=True)


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


def _req(path='/sso/autologin/', ip='203.0.113.9'):
    r = RequestFactory().get(path, HTTP_USER_AGENT='pytest-agent')
    r.META['REMOTE_ADDR'] = ip
    return r


@pytest.mark.django_db
class TestPayload:
    def test_carries_no_pii_and_nothing_beyond_user_and_scope(self, user):
        """django.core.signing is SIGNED, not encrypted — anyone holding the
        token can read this. It must contain only the bound user, the landing
        scope, the nonce and iat."""
        token = issue_token(user, scope='dashboard', request=_req())
        payload = signing.loads(token, salt=config.SIGNING_SALT)

        assert set(payload) == {'u', 's', 'n', 'iat'}
        assert payload['u'] == user.pk
        assert payload['s'] == 'dashboard'
        blob = str(payload).lower()
        for pii in (user.username.lower(), 'email', '@'):
            assert pii not in blob or pii == 'email' and 'email' not in blob

    def test_token_is_never_stored_only_its_hash(self, user):
        token = issue_token(user, request=_req())
        row = AutologinToken.objects.get(user=user)
        assert row.token_hash == token_hash(token)
        assert token not in row.token_hash
        assert not AutologinToken.objects.filter(token_hash=token).exists()


@pytest.mark.django_db
class TestSingleUse:
    def test_second_redemption_fails(self, user):
        token = issue_token(user, request=_req())
        redeem_token(token, _req())
        with pytest.raises(TokenAlreadyUsed):
            redeem_token(token, _req())

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_redemption_exactly_one_wins(self, user):
        """The race the atomic UPDATE...WHERE redeemed_at IS NULL exists for.

        transaction=True is required, not incidental: the default test wraps
        everything in one uncommitted transaction, so a second thread on its
        own connection cannot see the token at all and the "race" degenerates
        into TokenUnknown.

        serialized_rollback was tried here and REMOVED: it replays serialized
        initial data including contenttypes, which collide with the rows
        already present and fail the test at SETUP — green in isolation, error
        in a full run. The transactional flush this leaves behind is verified
        not to poison the alphabetically-later suites (tracker, user_profile,
        website); if that ever changes, this test is the cause to look at
        first.
        """
        token = issue_token(user, request=_req())

        def attempt():
            try:
                redeem_token(token, _req())
                return 'won'
            except TokenAlreadyUsed:
                return 'lost'
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))

        assert results.count('won') == 1, f'expected exactly one winner, got {results}'
        assert results.count('lost') == 1

    def test_burn_is_recorded_on_the_row(self, user):
        token = issue_token(user, request=_req())
        redeem_token(token, _req())
        row = AutologinToken.objects.get(user=user)
        assert row.redeemed_at is not None
        assert row.redeemed_ip == '203.0.113.9'


@pytest.mark.django_db
class TestRejections:
    def test_tampered_token_rejected(self, user):
        token = issue_token(user, request=_req())
        with pytest.raises(TokenTampered):
            redeem_token(token[:-3] + 'xyz', _req())

    def test_expired_token_rejected(self, user):
        with override_settings(SSO_TOKEN_TTL_SECONDS=1):
            token = issue_token(user, request=_req())
            time.sleep(1.2)
            with pytest.raises(TokenExpired):
                redeem_token(token, _req())

    def test_future_dated_token_rejected(self, user):
        """signing.loads(max_age=...) only catches OLD tokens — a future-dated
        one has negative age and sails through. Our own iat catches it."""
        future = int(timezone.now().timestamp()) + 3600
        forged = signing.dumps(
            {'u': user.pk, 's': 'dashboard', 'n': 'nonce-future', 'iat': future},
            salt=config.SIGNING_SALT)
        with pytest.raises(TokenFutureDated):
            redeem_token(forged, _req())

    def test_unknown_nonce_rejected(self, user):
        """Correctly signed but with no issuance record — e.g. a token minted
        by a host sharing SECRET_KEY but not this database."""
        from sso.service import TokenUnknown

        forged = signing.dumps(
            {'u': user.pk, 's': 'dashboard', 'n': 'never-issued',
             'iat': int(timezone.now().timestamp())},
            salt=config.SIGNING_SALT)
        with pytest.raises(TokenUnknown):
            redeem_token(forged, _req())

    def test_inactive_user_cannot_redeem(self, user):
        token = issue_token(user, request=_req())
        user.is_active = False
        user.save(update_fields=['is_active'])
        from sso.service import TokenUserUnusable
        with pytest.raises(TokenUserUnusable):
            redeem_token(token, _req())


@pytest.mark.django_db
class TestAuditIsWrittenOnFailureToo:
    """Only logging successes gives an audit trail blind to attacks."""

    @pytest.mark.parametrize('scenario,outcome', [
        ('tampered', AutologinAttempt.OUTCOME_TAMPERED),
        ('replay', AutologinAttempt.OUTCOME_ALREADY_USED),
        ('future', AutologinAttempt.OUTCOME_FUTURE_DATED),
    ])
    def test_failed_attempt_is_audited(self, user, scenario, outcome):
        if scenario == 'tampered':
            token = issue_token(user, request=_req())
            with pytest.raises(Exception):
                redeem_token(token[:-3] + 'zzz', _req())
        elif scenario == 'replay':
            token = issue_token(user, request=_req())
            redeem_token(token, _req())
            with pytest.raises(TokenAlreadyUsed):
                redeem_token(token, _req())
        else:
            forged = signing.dumps(
                {'u': user.pk, 's': 'd', 'n': 'x',
                 'iat': int(timezone.now().timestamp()) + 3600},
                salt=config.SIGNING_SALT)
            with pytest.raises(TokenFutureDated):
                redeem_token(forged, _req())

        assert AutologinAttempt.objects.filter(outcome=outcome).exists(), \
            f'{scenario} produced no audit row'

    def test_successful_redemption_is_audited(self, user):
        token = issue_token(user, request=_req())
        redeem_token(token, _req())
        row = AutologinAttempt.objects.get(outcome=AutologinAttempt.OUTCOME_REDEEMED)
        assert row.user_id == user.pk
        assert row.ip == '203.0.113.9'
        assert row.user_agent == 'pytest-agent'

    def test_audit_never_stores_the_token(self, user):
        token = issue_token(user, request=_req())
        redeem_token(token, _req())
        for row in AutologinAttempt.objects.all():
            assert row.token_hash != token
            assert token not in str(row.__dict__)


@pytest.mark.django_db
class TestRateLimits:
    def test_issuance_is_rate_limited_per_user(self, user):
        with override_settings(SSO_ISSUE_RATE_PER_HOUR=3):
            for _ in range(3):
                issue_token(user, request=_req())
            with pytest.raises(RateLimited):
                issue_token(user, request=_req())

    def test_redemption_is_rate_limited_per_ip(self, user):
        with override_settings(SSO_REDEEM_RATE_PER_HOUR=2):
            tokens = [issue_token(user, request=_req()) for _ in range(3)]
            redeem_token(tokens[0], _req(ip='198.51.100.7'))
            with pytest.raises(Exception):
                redeem_token(tokens[1], _req(ip='198.51.100.7'))
                redeem_token(tokens[2], _req(ip='198.51.100.7'))


@pytest.mark.django_db
class TestFailsClosedWhenStoreIsGone:
    """An unavailable nonce/rate store means single-use is unenforceable —
    worse than an outage. Never degrade to an in-memory or no-op path."""

    def test_issuance_fails_when_cache_is_down(self, user, monkeypatch):
        from django.core.cache import cache

        monkeypatch.setattr(cache, 'add', lambda *a, **k: (_ for _ in ()).throw(
            ConnectionError('redis gone')))
        with pytest.raises(StoreUnavailable):
            issue_token(user, request=_req())

    def test_redemption_fails_when_cache_is_down(self, user, monkeypatch):
        token = issue_token(user, request=_req())
        from django.core.cache import cache

        monkeypatch.setattr(cache, 'add', lambda *a, **k: (_ for _ in ()).throw(
            ConnectionError('redis gone')))
        with pytest.raises(StoreUnavailable):
            redeem_token(token, _req())
        assert AutologinToken.objects.get(pk=AutologinToken.objects.first().pk).redeemed_at is None


@pytest.mark.django_db
class TestRedirectHardening:
    def test_successful_redeem_redirects_with_hardened_headers(self, user):
        token = issue_token(user, request=_req())
        resp = Client().get('/sso/autologin/', {'token': token})

        assert resp.status_code == 302
        assert resp['Referrer-Policy'] == 'no-referrer'
        assert 'no-store' in resp['Cache-Control']
        assert 'noindex' in resp['X-Robots-Tag']

    def test_session_is_marked_as_autologin(self, user):
        token = issue_token(user, request=_req())
        client = Client()
        client.get('/sso/autologin/', {'token': token})
        assert client.session.get(SESSION_FLAG) is True

    def test_every_failure_is_404_not_403(self, user):
        """403 would confirm the feature exists and that the token was
        recognisably wrong. 404 tells a prober nothing."""
        token = issue_token(user, request=_req())
        client = Client()
        assert client.get('/sso/autologin/', {'token': token}).status_code == 302
        # replay
        assert Client().get('/sso/autologin/', {'token': token}).status_code == 404
        # tampered
        assert Client().get('/sso/autologin/', {'token': 'garbage'}).status_code == 404
        # missing
        assert Client().get('/sso/autologin/').status_code == 404

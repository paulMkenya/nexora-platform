"""
Tests for the Postback URL manager at /advertiser/postbacks/
and for HMAC verification in tracker/views.py postback().
"""
import hashlib
import hmac as _hmac
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from offer.models import Advertiser, AdvertiserPostbackKey
from tracker.models import HMAC_FAIL, HMAC_MISSING, HMAC_OK, HMAC_SKIP, InboundPostbackLog
from user_profile.models import Profile

from .factories import make_advertiser_user, make_click, make_offer

CELERY_PATCH = 'tracker.tasks.conversion.conversion.delay'
CACHES_DUMMY = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}


def _sig(secret, params):
    """Compute HMAC-SHA256 over sorted params (excluding 'sig')."""
    canonical = '&'.join(
        f'{k}={v}' for k, v in sorted(params.items()) if k != 'sig'
    )
    return _hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


# ── Postback manager UI ────────────────────────────────────────────────────

@override_settings(
    CACHES=CACHES_DUMMY,
    TRACKER_URL='https://t.cloudtrade.pro',
    ENFORCE_POSTBACK_HMAC=False,
)
class PostbackManagerTestCase(TestCase):
    def setUp(self):
        self.user, self.adv = make_advertiser_user('pbmgr')
        self.client.force_login(self.user)

    def test_page_returns_200(self):
        self.assertEqual(self.client.get('/advertiser/postbacks/').status_code, 200)

    def test_key_auto_created_on_first_visit(self):
        self.assertFalse(AdvertiserPostbackKey.objects.filter(advertiser=self.adv).exists())
        self.client.get('/advertiser/postbacks/')
        self.assertTrue(AdvertiserPostbackKey.objects.filter(advertiser=self.adv).exists())

    def test_key_not_duplicated_on_repeat_visits(self):
        self.client.get('/advertiser/postbacks/')
        self.client.get('/advertiser/postbacks/')
        self.assertEqual(AdvertiserPostbackKey.objects.filter(advertiser=self.adv).count(), 1)

    def test_canonical_url_in_context(self):
        r = self.client.get('/advertiser/postbacks/')
        self.assertIn('canonical_url', r.context)
        self.assertIn('t.cloudtrade.pro/postback', r.context['canonical_url'])
        self.assertIn('click_id', r.context['canonical_url'])

    def test_canonical_url_rendered(self):
        r = self.client.get('/advertiser/postbacks/')
        self.assertContains(r, 't.cloudtrade.pro/postback')
        self.assertContains(r, '{click_id}')

    def test_signed_url_in_context(self):
        r = self.client.get('/advertiser/postbacks/')
        self.assertIn('{sig}', r.context['signed_url'])

    def test_secret_not_rendered_in_plain_text_on_load(self):
        r = self.client.get('/advertiser/postbacks/')
        key = AdvertiserPostbackKey.objects.get(advertiser=self.adv)
        # Secret should be in the DOM (hidden span) but visually masked
        self.assertContains(r, key.secret)   # present in DOM for JS copy
        self.assertContains(r, 'secret-masked')  # masked element present

    def test_regenerate_creates_new_secret(self):
        self.client.get('/advertiser/postbacks/')  # create key
        key_before = AdvertiserPostbackKey.objects.get(advertiser=self.adv).secret
        self.client.post('/advertiser/postbacks/regenerate/')
        key_after = AdvertiserPostbackKey.objects.get(advertiser=self.adv).secret
        self.assertNotEqual(key_before, key_after)

    def test_regenerate_requires_post(self):
        r = self.client.get('/advertiser/postbacks/regenerate/')
        self.assertEqual(r.status_code, 405)

    def test_log_empty_state_shown(self):
        r = self.client.get('/advertiser/postbacks/')
        self.assertContains(r, 'No inbound postback attempts yet')

    def test_log_shows_own_entries(self):
        self.client.get('/advertiser/postbacks/')
        key = AdvertiserPostbackKey.objects.get(advertiser=self.adv)
        InboundPostbackLog.objects.create(
            advertiser=self.adv, click_id='abc123',
            hmac_status=HMAC_OK, response_code=200,
        )
        r = self.client.get('/advertiser/postbacks/')
        self.assertEqual(len(r.context['log']), 1)

    def test_log_excludes_other_advertiser_entries(self):
        self.client.get('/advertiser/postbacks/')
        _, other_adv = make_advertiser_user('otherpb')
        InboundPostbackLog.objects.create(
            advertiser=other_adv, click_id='xyz',
            hmac_status=HMAC_OK, response_code=200,
        )
        r = self.client.get('/advertiser/postbacks/')
        self.assertEqual(len(r.context['log']), 0)

    def test_unauthenticated_redirected(self):
        self.client.logout()
        r = self.client.get('/advertiser/postbacks/')
        self.assertRedirects(r, '/login/?next=/advertiser/postbacks/',
                             fetch_redirect_response=False)


# ── HMAC verification in tracker/views.postback() ─────────────────────────

@override_settings(CACHES=CACHES_DUMMY)
class PostbackHMACTestCase(TestCase):
    """
    Tests for HMAC verification logic in tracker/views.postback().
    All tests use mock for the conversion Celery task.
    """

    def setUp(self):
        self.user, self.adv = make_advertiser_user('hmacadv')
        self.offer = make_offer(self.adv, 'HMAC Offer')
        # A click that links back to our advertiser's offer
        self.click = self._make_real_click()
        self.key, _ = AdvertiserPostbackKey.objects.get_or_create(
            advertiser=self.adv,
            defaults={'secret': 'testsecret1234567890abcdef1234567890abcdef12345678'},
        )

    def _make_real_click(self):
        from tracker.models import Click
        return Click.objects.create(
            offer=self.offer,
            ip='1.2.3.4',
            revenue=Decimal('5.00'),
            payout=Decimal('3.00'),
        )

    def _postback_url(self, extra_params=''):
        return f'/postback?click_id={self.click.pk}&status=approved&sum=10{extra_params}'

    def _signed_url(self, params):
        sig = _sig(self.key.secret, params)
        qs = '&'.join(f'{k}={v}' for k, v in params.items())
        return f'/postback?{qs}&sig={sig}'

    # ── flag OFF (default) ─────────────────────────────────────────────────

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_no_sig_accepted_when_flag_off(self, mock_task):
        r = self.client.get(self._postback_url())
        self.assertEqual(r.status_code, 200)
        mock_task.assert_called_once()

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_bad_sig_accepted_when_flag_off(self, mock_task):
        r = self.client.get(self._postback_url('&sig=badhash'))
        self.assertEqual(r.status_code, 200)
        mock_task.assert_called_once()

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_valid_sig_accepted_when_flag_off(self, mock_task):
        params = {'click_id': str(self.click.pk), 'status': 'approved', 'sum': '10'}
        r = self.client.get(self._signed_url(params))
        self.assertEqual(r.status_code, 200)
        mock_task.assert_called_once()

    # ── flag ON ────────────────────────────────────────────────────────────

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=True)
    def test_valid_sig_accepted_when_flag_on(self, mock_task):
        params = {'click_id': str(self.click.pk), 'status': 'approved', 'sum': '10'}
        r = self.client.get(self._signed_url(params))
        self.assertEqual(r.status_code, 200)
        mock_task.assert_called_once()

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=True)
    def test_missing_sig_rejected_when_flag_on(self, mock_task):
        r = self.client.get(self._postback_url())
        self.assertEqual(r.status_code, 401)
        mock_task.assert_not_called()

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=True)
    def test_invalid_sig_rejected_when_flag_on(self, mock_task):
        r = self.client.get(self._postback_url('&sig=deadbeef'))
        self.assertEqual(r.status_code, 401)
        mock_task.assert_not_called()

    # ── logging ────────────────────────────────────────────────────────────

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_inbound_log_created_on_accepted_postback(self, mock_task):
        self.client.get(self._postback_url())
        self.assertEqual(InboundPostbackLog.objects.filter(advertiser=self.adv).count(), 1)

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=True)
    def test_inbound_log_created_on_rejected_postback(self, mock_task):
        self.client.get(self._postback_url('&sig=badhash'))
        log = InboundPostbackLog.objects.filter(advertiser=self.adv).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.response_code, 401)
        self.assertEqual(log.hmac_status, HMAC_FAIL)

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_hmac_ok_logged_for_valid_sig(self, mock_task):
        params = {'click_id': str(self.click.pk), 'status': 'approved', 'sum': '10'}
        self.client.get(self._signed_url(params))
        log = InboundPostbackLog.objects.filter(advertiser=self.adv).first()
        self.assertEqual(log.hmac_status, HMAC_OK)

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_hmac_missing_logged_when_no_sig(self, mock_task):
        self.client.get(self._postback_url())
        log = InboundPostbackLog.objects.filter(advertiser=self.adv).first()
        self.assertEqual(log.hmac_status, HMAC_MISSING)

    # ── existing behaviour unchanged ───────────────────────────────────────

    @patch(CELERY_PATCH)
    @override_settings(ENFORCE_POSTBACK_HMAC=False)
    def test_missing_click_id_returns_400(self, mock_task):
        r = self.client.get('/postback?status=approved&sum=10')
        self.assertEqual(r.status_code, 400)
        mock_task.assert_not_called()

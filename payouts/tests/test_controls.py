"""Withdrawal control layer — the provider-agnostic payout safety net.

Covers every part of the control layer at the dispatch boundary:
  A. velocity limits (per-tx, per-affiliate/day, per-brand/day, platform/day)
  B. threshold approval (park → operator approve dispatches; below-threshold flows)
  C. new/changed-address cool-down
  D. rule-based anomaly holds (large multiple + burst)
  E. audit trail + impersonation money-block composition + brand-scoped holds view
  F. config is read from the DB (UI), not env
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from brands.models import Brand
from payouts.models import (
    BrandWithdrawalControl, METHOD_CRYPTO, PayoutDecision, PayoutMethod,
    PayoutRequest, WithdrawalControlConfig,
    DECISION_ALLOWED, DECISION_APPROVED, DECISION_BLOCKED_LIMIT, DECISION_DENIED,
    DECISION_HELD_ANOMALY, DECISION_HELD_COOLDOWN, DECISION_HELD_THRESHOLD,
    STATUS_APPROVED, STATUS_BLOCKED, STATUS_DENIED,
    STATUS_PENDING_APPROVAL, STATUS_PROCESSING,
)
from user_profile.models import Profile, User


def _aged(dt_obj, **kwargs):
    return dt_obj - timedelta(**kwargs)


class ControlTestBase(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(
            slug='cb', name='CB', primary_domain='cb.test', tracking_domain='t.cb.test')
        self.cfg = WithdrawalControlConfig.load()
        # Generous defaults; each test tightens the knob it exercises so it is the
        # only rule that can fire. Cool-down off by default (set per cool-down test).
        self.cfg.enabled = True
        self.cfg.per_tx_max = Decimal('100000')
        self.cfg.per_affiliate_day_count = 0
        self.cfg.per_affiliate_day_amount = Decimal('0')
        self.cfg.per_brand_day_count = 0
        self.cfg.per_brand_day_amount = Decimal('0')
        self.cfg.platform_day_count = 0
        self.cfg.platform_day_amount = Decimal('0')
        self.cfg.approval_threshold = Decimal('0')
        self.cfg.new_address_cooldown_hours = 0
        self.cfg.anomaly_multiple = Decimal('0')
        self.cfg.anomaly_burst_count = 0
        self.cfg.save()

    def _affiliate(self, username, brand=None):
        u = User.objects.create_user(username, password='pass')
        p = u.profile
        p.role = Profile.Role.AFFILIATE
        p.brand = brand or self.brand
        p.save()
        return u

    _addr_seq = 0

    def _method(self, affiliate, *, age_hours=240):
        type(self)._addr_seq += 1
        pm = PayoutMethod.objects.create(
            affiliate=affiliate, method=METHOD_CRYPTO,
            details={'network': 'TRON', 'wallet_address': f'TX{self._addr_seq:06d}'})
        # PayoutMethod.created_at is auto_now_add; age it so cool-down is satisfied
        # unless a test deliberately uses a fresh address.
        PayoutMethod.objects.filter(pk=pm.pk).update(
            created_at=_aged(timezone.now(), hours=age_hours))
        pm.refresh_from_db()
        return pm

    def _request(self, affiliate, amount, *, method=None, status=STATUS_APPROVED):
        return PayoutRequest.objects.create(
            affiliate=affiliate, payout_method=method, amount=Decimal(str(amount)),
            method=METHOD_CRYPTO, status=status)

    def _dispatched(self, affiliate, amount, *, when=None):
        """A payout already released today — feeds the per-day velocity aggregates."""
        r = self._request(affiliate, amount, status=STATUS_PROCESSING)
        r.dispatched_at = when or timezone.now()
        r.save(update_fields=['dispatched_at', 'status'])
        return r


# A crypto provider stub that always "succeeds" so allowed payouts dispatch.
def _patch_dispatch_success():
    def _fake(req):
        req.status = STATUS_PROCESSING
        req.tx_ref = 'tx-fake'
        return True
    return mock.patch('payouts.providers.dispatch.dispatch_payout', side_effect=_fake)


# --- Part A: velocity limits ----------------------------------------------


class VelocityLimitTests(ControlTestBase):
    def test_per_transaction_max_blocks(self):
        self.cfg.per_tx_max = Decimal('500')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req = self._request(aff, 600, method=self._method(aff))
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_BLOCKED)
        self.assertIsNone(req.dispatched_at)

    def test_per_transaction_max_allows_at_or_below(self):
        self.cfg.per_tx_max = Decimal('500')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req = self._request(aff, 500, method=self._method(aff))
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)

    def test_per_affiliate_day_count_blocks(self):
        self.cfg.per_affiliate_day_count = 2
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        self._dispatched(aff, 10)
        self._dispatched(aff, 10)  # 2 already today
        req = self._request(aff, 10, method=self._method(aff))
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)
        self.assertEqual(PayoutRequest.objects.get(pk=req.pk).status, STATUS_BLOCKED)

    def test_per_affiliate_day_amount_blocks(self):
        self.cfg.per_affiliate_day_amount = Decimal('100')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        self._dispatched(aff, 80)
        req = self._request(aff, 30, method=self._method(aff))  # 80+30 > 100
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)

    def test_per_brand_day_amount_blocks_across_affiliates(self):
        self.cfg.per_brand_day_amount = Decimal('100')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        a1 = self._affiliate('a1')
        a2 = self._affiliate('a2')
        self._dispatched(a1, 90)  # same brand
        req = self._request(a2, 20, method=self._method(a2))  # 90+20 > 100
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)

    def test_per_brand_limit_isolated_between_brands(self):
        """One brand's daily total must not count against another brand's cap."""
        self.cfg.per_brand_day_amount = Decimal('100')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        other = Brand.objects.create(
            slug='ob', name='OB', primary_domain='ob.test', tracking_domain='t.ob.test')
        a1 = self._affiliate('a1')  # self.brand
        a2 = self._affiliate('a2', brand=other)
        self._dispatched(a1, 90)  # fills self.brand
        req = self._request(a2, 50, method=self._method(a2))  # other brand: clean
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)

    def test_platform_day_count_blocks(self):
        self.cfg.platform_day_count = 1
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        a1 = self._affiliate('a1')
        a2 = self._affiliate('a2')
        self._dispatched(a1, 10)  # platform already at 1
        req = self._request(a2, 10, method=self._method(a2))
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)


# --- Part B: threshold approval -------------------------------------------


class ThresholdApprovalTests(ControlTestBase):
    def test_above_threshold_parks_pending_approval(self):
        self.cfg.approval_threshold = Decimal('1000')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req = self._request(aff, 1500, method=self._method(aff))
        with _patch_dispatch_success() as m:
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_HELD_THRESHOLD)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PENDING_APPROVAL)
        self.assertIsNone(req.dispatched_at)
        m.assert_not_called()  # provider never touched while parked

    def test_below_threshold_dispatches_normally(self):
        self.cfg.approval_threshold = Decimal('1000')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req = self._request(aff, 999, method=self._method(aff))
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)
        self.assertIsNotNone(req.dispatched_at)

    def test_approval_dispatches_parked_payout(self):
        self.cfg.approval_threshold = Decimal('1000')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch, approve
        aff = self._affiliate('a1')
        operator = User.objects.create_user('op', password='pass', is_staff=True)
        req = self._request(aff, 1500, method=self._method(aff))
        enforce_and_dispatch(req)  # parks it
        self.assertEqual(PayoutRequest.objects.get(pk=req.pk).status, STATUS_PENDING_APPROVAL)
        with _patch_dispatch_success():
            out = approve(req, operator, reason='looks legit')
        self.assertEqual(out.decision, DECISION_ALLOWED)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)
        self.assertIsNotNone(req.dispatched_at)
        # The approval itself is audited (who/amount/reason).
        appr = PayoutDecision.objects.filter(
            payout_request=req, decision=DECISION_APPROVED).first()
        self.assertIsNotNone(appr)
        self.assertEqual(appr.actor, operator)
        self.assertEqual(appr.amount, Decimal('1500.00'))

    def test_denied_payout_never_dispatches(self):
        self.cfg.approval_threshold = Decimal('1000')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch, deny
        aff = self._affiliate('a1')
        operator = User.objects.create_user('op', password='pass', is_staff=True)
        req = self._request(aff, 1500, method=self._method(aff))
        enforce_and_dispatch(req)
        out = deny(req, operator, reason='suspicious')
        self.assertEqual(out.decision, DECISION_DENIED)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_DENIED)
        self.assertIsNone(req.dispatched_at)

    def test_approval_still_enforces_velocity_limits(self):
        """A human approval cannot blow past a hard daily cap."""
        self.cfg.approval_threshold = Decimal('1000')
        self.cfg.per_affiliate_day_amount = Decimal('1200')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch, approve
        aff = self._affiliate('a1')
        operator = User.objects.create_user('op', password='pass', is_staff=True)
        req = self._request(aff, 1500, method=self._method(aff))
        enforce_and_dispatch(req)  # parked (threshold)
        out = approve(req, operator)  # 1500 > 1200 cap
        self.assertEqual(out.decision, DECISION_BLOCKED_LIMIT)
        self.assertEqual(PayoutRequest.objects.get(pk=req.pk).status, STATUS_BLOCKED)


# --- Part C: new-address cool-down ----------------------------------------


class CooldownTests(ControlTestBase):
    def test_new_address_within_cooldown_holds(self):
        self.cfg.new_address_cooldown_hours = 24
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        fresh = self._method(aff, age_hours=1)  # established 1h ago
        req = self._request(aff, 50, method=fresh)
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_HELD_COOLDOWN)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PENDING_APPROVAL)
        self.assertIsNotNone(req.control_hold_until)

    def test_aged_address_passes_cooldown(self):
        self.cfg.new_address_cooldown_hours = 24
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        old = self._method(aff, age_hours=48)
        req = self._request(aff, 50, method=old)
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)


# --- Part D: anomaly holds -------------------------------------------------


class AnomalyTests(ControlTestBase):
    def test_large_multiple_of_history_holds(self):
        self.cfg.anomaly_multiple = Decimal('5')
        self.cfg.anomaly_min_history = 3
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        for _ in range(3):  # history avg ~100
            self._dispatched(aff, 100, when=_aged(timezone.now(), days=5))
        req = self._request(aff, 1000, method=self._method(aff))  # 10x avg
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_HELD_ANOMALY)
        self.assertEqual(PayoutRequest.objects.get(pk=req.pk).status, STATUS_PENDING_APPROVAL)

    def test_normal_amount_with_history_passes(self):
        self.cfg.anomaly_multiple = Decimal('5')
        self.cfg.anomaly_min_history = 3
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        for _ in range(3):
            self._dispatched(aff, 100, when=_aged(timezone.now(), days=5))
        req = self._request(aff, 150, method=self._method(aff))  # 1.5x avg, fine
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)

    def test_burst_of_requests_holds(self):
        self.cfg.anomaly_burst_count = 3
        self.cfg.anomaly_burst_window_minutes = 60
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        self._request(aff, 10)
        self._request(aff, 10)  # 2 recent requests already
        req = self._request(aff, 10, method=self._method(aff))  # 3rd within window
        out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_HELD_ANOMALY)


# --- Config source + master switch ----------------------------------------


class ConfigSourceTests(ControlTestBase):
    def test_limits_read_from_db_not_env(self):
        """Changing the DB row changes enforcement live — no env, no redeploy."""
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req1 = self._request(aff, 600, method=self._method(aff))
        with _patch_dispatch_success():
            self.assertTrue(enforce_and_dispatch(req1).allowed)
        # Tighten the limit in the DB; a new payout of the same size is now blocked.
        self.cfg.per_tx_max = Decimal('500')
        self.cfg.save()
        req2 = self._request(aff, 600, method=self._method(aff))
        self.assertEqual(enforce_and_dispatch(req2).decision, DECISION_BLOCKED_LIMIT)

    def test_brand_override_takes_precedence(self):
        from payouts.control import resolve_config
        self.cfg.approval_threshold = Decimal('5000')
        self.cfg.save()
        BrandWithdrawalControl.objects.create(
            brand=self.brand, approval_threshold=Decimal('100'))
        resolved = resolve_config(self.brand)
        self.assertEqual(resolved.approval_threshold, Decimal('100'))

    def test_master_switch_off_allows_everything(self):
        self.cfg.enabled = False
        self.cfg.per_tx_max = Decimal('1')
        self.cfg.save()
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')
        req = self._request(aff, 9999, method=self._method(aff))
        with _patch_dispatch_success():
            out = enforce_and_dispatch(req)
        self.assertEqual(out.decision, DECISION_ALLOWED)


# --- Part E: audit trail ---------------------------------------------------


class AuditTests(ControlTestBase):
    def test_every_decision_is_audited(self):
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('a1')

        # allowed
        r_ok = self._request(aff, 10, method=self._method(aff))
        with _patch_dispatch_success():
            enforce_and_dispatch(r_ok)
        self.assertTrue(PayoutDecision.objects.filter(
            payout_request=r_ok, decision=DECISION_ALLOWED).exists())

        # blocked
        self.cfg.per_tx_max = Decimal('5')
        self.cfg.save()
        r_block = self._request(aff, 50, method=self._method(aff))
        enforce_and_dispatch(r_block)
        d = PayoutDecision.objects.get(
            payout_request=r_block, decision=DECISION_BLOCKED_LIMIT)
        self.assertIn('per-transaction max', d.reason)
        self.assertEqual(d.amount, Decimal('50.00'))
        self.assertEqual(d.brand, self.brand)


# --- Impersonation money-block composition + brand-scoped holds view -------


class HoldsViewAndImpersonationTests(ControlTestBase):
    def setUp(self):
        super().setUp()
        self.other = Brand.objects.create(
            slug='ob', name='OB', primary_domain='ob.test', tracking_domain='t.ob.test')
        self.aff_a = self._affiliate('aff_a', brand=self.brand)
        self.aff_b = self._affiliate('aff_b', brand=self.other)
        self.held_a = self._request(self.aff_a, 50, status=STATUS_PENDING_APPROVAL)
        self.held_b = self._request(self.aff_b, 50, status=STATUS_PENDING_APPROVAL)

        self.admin_a = User.objects.create_user('admin_a', password='pass', is_staff=True)
        pa = self.admin_a.profile
        pa.role = Profile.Role.NETWORK_ADMIN
        pa.brand = self.brand
        pa.save()
        self.superuser = User.objects.create_superuser('root', 'root@test.com', 'pass')

    def test_holds_view_is_brand_scoped(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/payouts/holds/', HTTP_HOST='cb.test')
        self.assertEqual(r.status_code, 200)
        ids = {pr.pk for pr in r.context['requests']}
        self.assertIn(self.held_a.pk, ids)
        self.assertNotIn(self.held_b.pk, ids)

    def test_superuser_sees_all_holds(self):
        self.client.force_login(self.superuser)
        r = self.client.get('/admin/payouts/holds/', HTTP_HOST='cb.test')
        ids = {pr.pk for pr in r.context['requests']}
        self.assertIn(self.held_a.pk, ids)
        self.assertIn(self.held_b.pk, ids)

    def test_brand_admin_cannot_approve_other_brand_hold(self):
        self.client.force_login(self.admin_a)
        with _patch_dispatch_success():
            r = self.client.post(
                f'/admin/payouts/holds/{self.held_b.pk}/approve/', {}, HTTP_HOST='cb.test')
        self.assertEqual(r.status_code, 302)
        self.held_b.refresh_from_db()
        self.assertEqual(self.held_b.status, STATUS_PENDING_APPROVAL)  # untouched

    def test_impersonator_cannot_approve_hold(self):
        """The impersonation money-block composes with the control layer:
        an impersonated session can't trigger a payout at all. A request flagged
        is_impersonating is refused (403) before any approval runs."""
        from django.test import RequestFactory
        from payouts.views.admin_views import approve_hold
        rf = RequestFactory()
        post = rf.post(f'/admin/payouts/holds/{self.held_a.pk}/approve/')
        post.user = self.admin_a
        post.is_impersonating = True
        resp = approve_hold(post, pk=self.held_a.pk)
        self.assertEqual(resp.status_code, 403)
        self.held_a.refresh_from_db()
        self.assertEqual(self.held_a.status, STATUS_PENDING_APPROVAL)

    def test_impersonator_cannot_dispatch(self):
        from django.test import RequestFactory
        from payouts.views.admin_views import dispatch_approved
        rf = RequestFactory()
        post = rf.post('/admin/payouts/dispatch/')
        post.user = self.superuser
        post.is_impersonating = True
        resp = dispatch_approved(post)
        self.assertEqual(resp.status_code, 403)

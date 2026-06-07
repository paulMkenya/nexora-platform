"""The withdrawal control layer — provider-agnostic payout safety net.

This module is the single enforcement point that sits BETWEEN "payout approved"
and "funds actually move". Every payout — fiat or crypto — passes through
:func:`enforce_and_dispatch` at the dispatch boundary; nothing reaches a provider
without being evaluated here first. The layer wraps whatever payout provider is
configured (it never integrates one itself), so a compromised account, a single
mistake, or a flood of requests cannot drain funds.

Decision precedence (deterministic, explainable — no ML):

  1. Velocity limits (Part A) — HARD BLOCK. A payout exceeding the per-transaction
     max, the per-affiliate/day, per-brand/day or platform/day count/amount cap is
     refused (``blocked``), never silently capped.
  2. New/changed-address cool-down (Part C) — time HOLD until the destination has
     aged past the configured window.
  3. Threshold approval (Part B) — amounts at/above the threshold park in
     ``pending_approval`` for an authorized operator.
  4. Anomaly rules (Part D) — a payout that is a large multiple of the affiliate's
     historical average, or part of a sudden burst, parks in ``pending_approval``.
  5. Otherwise — ALLOWED, dispatched through the configured provider.

Configuration is read live from the database (:class:`WithdrawalControlConfig`
plus optional per-:class:`BrandWithdrawalControl` overrides) — never from env —
so the owner edits it in the UI. Every decision is written to
:class:`PayoutDecision`.

This composes with — and never replaces — the impersonation money-block: the
operator views that call into this layer are wrapped with
``block_when_impersonating``, so an impersonator can't trigger a payout at all,
and this layer guards everything that does get through.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import Count, Sum
from django.utils import timezone

from payouts.models import (
    BrandWithdrawalControl, PayoutDecision, PayoutRequest, WithdrawalControlConfig,
    DECISION_ALLOWED, DECISION_APPROVED, DECISION_BLOCKED_LIMIT,
    DECISION_DENIED, DECISION_DISPATCH_FAILED, DECISION_HELD_ANOMALY,
    DECISION_HELD_COOLDOWN, DECISION_HELD_THRESHOLD,
    STATUS_BLOCKED, STATUS_DENIED, STATUS_PENDING_APPROVAL,
)

logger = logging.getLogger(__name__)


# --- resolved configuration ------------------------------------------------


@dataclass(frozen=True)
class ControlConfig:
    """The effective config for one brand: global defaults with brand overrides."""
    enabled: bool
    per_tx_max: Decimal
    per_affiliate_day_count: int
    per_affiliate_day_amount: Decimal
    per_brand_day_count: int
    per_brand_day_amount: Decimal
    platform_day_count: int
    platform_day_amount: Decimal
    approval_threshold: Decimal
    new_address_cooldown_hours: int
    anomaly_multiple: Decimal
    anomaly_min_history: int
    anomaly_burst_count: int
    anomaly_burst_window_minutes: int


def _pick(override_val, default_val):
    return default_val if override_val is None else override_val


def resolve_config(brand) -> ControlConfig:
    """Merge the platform config with any per-brand override for ``brand``."""
    g = WithdrawalControlConfig.load()
    o = None
    if brand is not None:
        o = BrandWithdrawalControl.objects.filter(brand=brand).first()
    if o is None:
        return ControlConfig(
            enabled=g.enabled,
            per_tx_max=g.per_tx_max,
            per_affiliate_day_count=g.per_affiliate_day_count,
            per_affiliate_day_amount=g.per_affiliate_day_amount,
            per_brand_day_count=g.per_brand_day_count,
            per_brand_day_amount=g.per_brand_day_amount,
            platform_day_count=g.platform_day_count,
            platform_day_amount=g.platform_day_amount,
            approval_threshold=g.approval_threshold,
            new_address_cooldown_hours=g.new_address_cooldown_hours,
            anomaly_multiple=g.anomaly_multiple,
            anomaly_min_history=g.anomaly_min_history,
            anomaly_burst_count=g.anomaly_burst_count,
            anomaly_burst_window_minutes=g.anomaly_burst_window_minutes,
        )
    return ControlConfig(
        enabled=g.enabled,
        per_tx_max=_pick(o.per_tx_max, g.per_tx_max),
        per_affiliate_day_count=_pick(o.per_affiliate_day_count, g.per_affiliate_day_count),
        per_affiliate_day_amount=_pick(o.per_affiliate_day_amount, g.per_affiliate_day_amount),
        per_brand_day_count=_pick(o.per_brand_day_count, g.per_brand_day_count),
        per_brand_day_amount=_pick(o.per_brand_day_amount, g.per_brand_day_amount),
        platform_day_count=g.platform_day_count,
        platform_day_amount=g.platform_day_amount,
        approval_threshold=_pick(o.approval_threshold, g.approval_threshold),
        new_address_cooldown_hours=_pick(o.new_address_cooldown_hours, g.new_address_cooldown_hours),
        anomaly_multiple=_pick(o.anomaly_multiple, g.anomaly_multiple),
        anomaly_min_history=g.anomaly_min_history,
        anomaly_burst_count=g.anomaly_burst_count,
        anomaly_burst_window_minutes=g.anomaly_burst_window_minutes,
    )


# --- evaluation ------------------------------------------------------------


@dataclass
class Outcome:
    decision: str
    reason: str = ''
    hold_until: Optional[datetime] = None

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOWED

    @property
    def blocked(self) -> bool:
        return self.decision == DECISION_BLOCKED_LIMIT

    @property
    def held(self) -> bool:
        return self.decision in (
            DECISION_HELD_THRESHOLD, DECISION_HELD_COOLDOWN, DECISION_HELD_ANOMALY,
        )


def brand_of(req) -> Optional[object]:
    """The brand a payout belongs to — its affiliate's Profile.brand."""
    prof = getattr(req.affiliate, 'profile', None)
    return getattr(prof, 'brand', None)


def _day_bounds(now):
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _positive(value) -> bool:
    """A limit is active only when it is set to a positive number."""
    return value is not None and value > 0


def _check_velocity(req, cfg, amount, now) -> Optional[Outcome]:
    """Part A — hard velocity limits. Returns a BLOCKED outcome or None."""
    if _positive(cfg.per_tx_max) and amount > cfg.per_tx_max:
        return Outcome(
            DECISION_BLOCKED_LIMIT,
            f'amount {amount} exceeds per-transaction max {cfg.per_tx_max}')

    day_start, day_end = _day_bounds(now)
    dispatched_today = PayoutRequest.objects.filter(
        dispatched_at__gte=day_start, dispatched_at__lt=day_end,
    ).exclude(pk=req.pk)

    scopes = [
        (dispatched_today.filter(affiliate=req.affiliate),
         cfg.per_affiliate_day_count, cfg.per_affiliate_day_amount, 'per-affiliate/day'),
    ]
    brand = brand_of(req)
    if brand is not None:
        scopes.append((
            dispatched_today.filter(affiliate__profile__brand=brand),
            cfg.per_brand_day_count, cfg.per_brand_day_amount, 'per-brand/day'))
    scopes.append((
        dispatched_today, cfg.platform_day_count, cfg.platform_day_amount, 'platform/day'))

    for qs, count_limit, amount_limit, label in scopes:
        agg = qs.aggregate(c=Count('id'), s=Sum('amount'))
        used_count = agg['c'] or 0
        used_sum = agg['s'] or Decimal('0')
        if _positive(count_limit) and used_count + 1 > count_limit:
            return Outcome(
                DECISION_BLOCKED_LIMIT,
                f'{label} count limit {count_limit} reached ({used_count} already today)')
        if _positive(amount_limit) and used_sum + amount > amount_limit:
            return Outcome(
                DECISION_BLOCKED_LIMIT,
                f'{label} amount limit {amount_limit} exceeded '
                f'({used_sum} already + {amount})')
    return None


def _check_holds(req, cfg, amount, now) -> Optional[Outcome]:
    """Parts C/B/D — cool-down, threshold, anomaly. Returns a HELD outcome or None."""
    # C. New/changed-address cool-down.
    pm = req.payout_method
    if pm is not None and _positive(cfg.new_address_cooldown_hours):
        hold_until = pm.created_at + timedelta(hours=cfg.new_address_cooldown_hours)
        if now < hold_until:
            return Outcome(
                DECISION_HELD_COOLDOWN,
                f'payout destination established {pm.created_at:%Y-%m-%d %H:%M} is within '
                f'the {cfg.new_address_cooldown_hours}h cool-down (until {hold_until:%Y-%m-%d %H:%M})',
                hold_until=hold_until)

    # B. Threshold approval.
    if _positive(cfg.approval_threshold) and amount >= cfg.approval_threshold:
        return Outcome(
            DECISION_HELD_THRESHOLD,
            f'amount {amount} is at/above the approval threshold {cfg.approval_threshold}')

    # D. Anomaly — large multiple of the affiliate's historical average.
    if _positive(cfg.anomaly_multiple):
        agg = PayoutRequest.objects.filter(
            affiliate=req.affiliate, dispatched_at__isnull=False,
        ).exclude(pk=req.pk).aggregate(c=Count('id'), s=Sum('amount'))
        hist_count = agg['c'] or 0
        if hist_count >= cfg.anomaly_min_history:
            avg = (agg['s'] or Decimal('0')) / hist_count
            if avg > 0 and amount > avg * cfg.anomaly_multiple:
                return Outcome(
                    DECISION_HELD_ANOMALY,
                    f'amount {amount} is {(amount / avg):.1f}x the affiliate historical '
                    f'average {avg:.2f} (limit {cfg.anomaly_multiple}x)')

    # D. Anomaly — sudden burst of payout requests.
    if _positive(cfg.anomaly_burst_count):
        window_start = now - timedelta(minutes=cfg.anomaly_burst_window_minutes)
        burst = PayoutRequest.objects.filter(
            affiliate=req.affiliate, created_at__gte=window_start,
        ).count()
        if burst >= cfg.anomaly_burst_count:
            return Outcome(
                DECISION_HELD_ANOMALY,
                f'{burst} payout requests within {cfg.anomaly_burst_window_minutes}m '
                f'(burst limit {cfg.anomaly_burst_count})')
    return None


def evaluate(req: PayoutRequest, cfg: ControlConfig, *, skip_holds: bool = False) -> Outcome:
    """Decide what should happen to ``req`` — pure, deterministic, side-effect free.

    ``skip_holds`` bypasses the threshold / cool-down / anomaly *holds* (used when
    an authorized operator has manually approved a parked payout) but NEVER
    bypasses the hard velocity limits — a human approval still can't blow past the
    platform's daily caps.
    """
    if not cfg.enabled:
        return Outcome(DECISION_ALLOWED, 'control layer disabled')

    amount = Decimal(req.amount)
    now = timezone.now()

    blocked = _check_velocity(req, cfg, amount, now)
    if blocked is not None:
        return blocked

    if skip_holds:
        return Outcome(DECISION_ALLOWED, 'operator-approved; velocity limits cleared')

    held = _check_holds(req, cfg, amount, now)
    if held is not None:
        return held

    return Outcome(DECISION_ALLOWED, 'within all withdrawal controls')


# --- enforcement at the dispatch boundary ----------------------------------


def _log(req, outcome, *, actor=None, decision=None, reason=None):
    PayoutDecision.objects.create(
        payout_request=req,
        decision=decision or outcome.decision,
        reason=reason if reason is not None else outcome.reason,
        amount=req.amount,
        brand=brand_of(req),
        actor=actor,
    )


def enforce_and_dispatch(req: PayoutRequest, *, actor=None, skip_holds: bool = False) -> Outcome:
    """Evaluate ``req`` and either dispatch it or park it — the dispatch boundary.

    This is the ONLY sanctioned way to move a payout to a provider. Returns the
    :class:`Outcome`; the request's status is updated and persisted, and the
    decision is audited, before this returns.
    """
    from payouts.providers.dispatch import dispatch_payout

    cfg = resolve_config(brand_of(req))
    outcome = evaluate(req, cfg, skip_holds=skip_holds)

    if outcome.allowed:
        ok = dispatch_payout(req)
        if ok:
            req.dispatched_at = timezone.now()
            req.control_hold_until = None
            req.save()
            _log(req, outcome)
            logger.info('payout #%s ALLOWED + dispatched: %s', req.pk, outcome.reason)
        else:
            # The provider refused / errored; dispatch_payout set status=failed.
            req.save()
            _log(req, outcome, decision=DECISION_DISPATCH_FAILED,
                 reason=req.notes or 'provider dispatch failed')
            logger.warning('payout #%s dispatch FAILED: %s', req.pk, req.notes)
        return outcome

    if outcome.blocked:
        req.status = STATUS_BLOCKED
        req.notes = outcome.reason
        req.control_hold_until = None
        req.save()
        _log(req, outcome)
        logger.warning('payout #%s BLOCKED by velocity limit: %s', req.pk, outcome.reason)
        return outcome

    # Held — park for human/time review.
    req.status = STATUS_PENDING_APPROVAL
    req.control_hold_until = outcome.hold_until
    req.notes = outcome.reason
    req.save()
    _log(req, outcome)
    logger.info('payout #%s HELD (%s): %s', req.pk, outcome.decision, outcome.reason)
    return outcome


def approve(req: PayoutRequest, actor, *, reason: str = '') -> Outcome:
    """An authorized operator approves a parked payout; dispatch it now.

    The approval itself is audited (who/when/amount/reason). Holds (threshold,
    cool-down, anomaly) are released, but the hard velocity limits are still
    enforced — approval cannot push the platform past its daily caps.
    """
    _log(req, Outcome(DECISION_APPROVED, reason), actor=actor,
         decision=DECISION_APPROVED, reason=reason or 'operator approved')
    return enforce_and_dispatch(req, actor=actor, skip_holds=True)


def deny(req: PayoutRequest, actor, *, reason: str = '') -> Outcome:
    """An authorized operator denies a parked payout. Audited; never dispatched."""
    req.status = STATUS_DENIED
    req.notes = reason or 'operator denied'
    req.control_hold_until = None
    req.save()
    outcome = Outcome(DECISION_DENIED, reason or 'operator denied')
    _log(req, outcome, actor=actor)
    logger.info('payout #%s DENIED by %s: %s', req.pk, getattr(actor, 'pk', '?'), reason)
    return outcome

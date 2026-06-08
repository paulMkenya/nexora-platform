"""
Dispatch a PayoutRequest to the correct provider.
Each provider is feature-flagged via env vars (blank = disabled).

Crypto note: this module is reached ONLY beneath ``payouts.control.enforce_and_dispatch``
(the single sanctioned dispatch boundary). Nothing here may be called in a way that
bypasses the control layer. The crypto path is additionally gated by the
``CRYPTO_DISPATCH_ENABLED`` kill-switch (checked first in :func:`_dispatch_crypto`)
and, inside the NOWPayments client, the ``NOWPAYMENTS_ALLOW_MAINNET`` guard.
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

# The only supported crypto payout provider. NOWPayments is the guarded Mass
# Payouts client (create_payout / verify_payout). Kept as an allowlist so a config
# typo on this money path fails loud instead of silently routing somewhere.
SUPPORTED_CRYPTO_PROVIDERS = frozenset({'nowpayments'})


def get_crypto_provider():
    """Return the configured crypto provider instance (always the NOWPayments client).

    ``CRYPTO_PAYOUT_PROVIDER`` is validated against an allowlist: any value other
    than a supported provider raises :class:`~django.core.exceptions.ImproperlyConfigured`
    at call time rather than silently defaulting — a config typo on a money path
    must not route anywhere.
    """
    provider_name = getattr(settings, 'CRYPTO_PAYOUT_PROVIDER', 'nowpayments')
    if provider_name not in SUPPORTED_CRYPTO_PROVIDERS:
        raise ImproperlyConfigured(
            f'Unknown CRYPTO_PAYOUT_PROVIDER {provider_name!r}. Supported: '
            f'{sorted(SUPPORTED_CRYPTO_PROVIDERS)}.')
    from payouts.providers.nowpayments import NowPaymentsPayoutClient
    return NowPaymentsPayoutClient()


def dispatch_payout(payout_request) -> bool:
    """
    Send a payout request through the appropriate provider.
    Returns True if dispatched successfully, False otherwise.
    Updates payout_request.status and tx_ref in-place (caller must save).
    """
    from payouts.models import METHOD_CRYPTO, STATUS_FAILED
    method = payout_request.method
    pm = payout_request.payout_method

    try:
        if method == METHOD_CRYPTO:
            return _dispatch_crypto(payout_request, pm)
        if method == 'wise':
            return _dispatch_wise(payout_request, pm)
        if method == 'mpesa':
            return _dispatch_mpesa(payout_request, pm)
        if method == 'paypal':
            return _dispatch_paypal(payout_request, pm)
        if method == 'paxum':
            return _dispatch_paxum(payout_request, pm)
        logger.warning('No provider for method %s', method)
        return False
    except Exception as exc:
        logger.error('dispatch_payout error req=%s: %s', payout_request.pk, exc)
        payout_request.status = STATUS_FAILED
        return False


def _dispatch_crypto(payout_request, pm) -> bool:
    """Dispatch a crypto payout. Reached only beneath ``enforce_and_dispatch``.

    Gate order (both must pass for any real send):
      1. ``CRYPTO_DISPATCH_ENABLED`` kill-switch — checked FIRST, before any
         provider is constructed or called. When off, this no-ops: the payout
         keeps its current state and nothing reaches the provider.
      2. ``NOWPAYMENTS_ALLOW_MAINNET`` — enforced inside the client on init.
    """
    # --- Gate 1: kill-switch (key-independent) ---------------------------------
    if not getattr(settings, 'CRYPTO_DISPATCH_ENABLED', False):
        msg = 'crypto dispatch disabled (CRYPTO_DISPATCH_ENABLED is off)'
        logger.info(
            'Crypto dispatch DISABLED — no-op for req %s: %s', payout_request.pk, msg)
        # Leave status untouched; set a clearly-distinguishable note so the benign
        # control-layer audit row reads "disabled", not a real provider failure.
        payout_request.notes = msg
        return False

    # get_crypto_provider() always returns the NOWPayments Mass Payouts client (or
    # raises ImproperlyConfigured on a bad CRYPTO_PAYOUT_PROVIDER — caught above in
    # dispatch_payout and surfaced as a failed dispatch).
    provider = get_crypto_provider()
    return _dispatch_crypto_nowpayments(provider, payout_request, pm)


def _crypto_destination(pm):
    """Resolve (currency, address) from the payout method.

    Currency comes from the method's ``network`` label, falling back to
    ``NOWPAYMENTS_DEFAULT_CURRENCY`` when no network is set.
    """
    from payouts.providers.nowpayments.payouts import network_to_currency
    details = pm.details if pm else {}
    network = details.get('network', '')
    address = details.get('wallet_address', '')
    currency = (
        network_to_currency(network) if network
        else getattr(settings, 'NOWPAYMENTS_DEFAULT_CURRENCY', 'usdttrc20'))
    return currency, address


def _extract_provider_ids(resp):
    """Pull ``(batch_id, withdrawal_id)`` from a create_payout response.

    Shape: ``{'id': <batch id>, 'withdrawals': [{'id': <withdrawal id>, ...}]}``.
    Returns empty strings for anything missing.
    """
    resp = resp or {}
    batch_id = resp.get('id') or resp.get('batch_id') or ''
    withdrawal_id = ''
    withdrawals = resp.get('withdrawals')
    if isinstance(withdrawals, list) and withdrawals:
        withdrawal_id = (withdrawals[0] or {}).get('id', '')
    return str(batch_id) if batch_id else '', str(withdrawal_id) if withdrawal_id else ''


def _dispatch_crypto_nowpayments(client, payout_request, pm) -> bool:
    """Create + verify a single-withdrawal NOWPayments batch for this request.

    Outbound idempotency: if the request already carries provider ids we resume
    (poll) rather than create a second batch — a double-send must be impossible.
    """
    from django.utils import timezone
    from payouts.models import CryptoPayoutBatch, STATUS_PROCESSING, STATUS_FAILED
    from payouts.providers.nowpayments import NowPaymentsError

    # --- outbound idempotency guard --------------------------------------------
    if payout_request.provider_batch_id or payout_request.provider_withdrawal_id:
        logger.info(
            'Crypto req %s already has provider ids (batch=%s withdrawal=%s) — '
            'resuming, NOT re-creating (outbound idempotency).',
            payout_request.pk, payout_request.provider_batch_id,
            payout_request.provider_withdrawal_id)
        payout_request.status = STATUS_PROCESSING
        return True

    currency, address = _crypto_destination(pm)
    amount = Decimal(payout_request.amount)

    # 1. Create the one-entry batch. extra_id correlates the IPN to this request.
    create_resp = client.create_payout(
        address=address, currency=currency, amount=amount,
        extra_id=str(payout_request.pk))
    batch_id, withdrawal_id = _extract_provider_ids(create_resp)
    if not batch_id:
        payout_request.status = STATUS_FAILED
        payout_request.notes = 'NOWPayments create_payout returned no batch id'
        logger.error('Crypto req %s: create_payout missing batch id: %s',
                     payout_request.pk, create_resp)
        return False

    # 2. Persist the batch + idempotency anchor BEFORE verify, so a crash mid-verify
    #    can never strand us into creating a second batch on a later run.
    batch = CryptoPayoutBatch.objects.create(
        provider='nowpayments', provider_batch_id=str(batch_id), status='created',
        currency=currency, total_amount=amount, raw_create_response=create_resp)
    payout_request.provider_batch = batch
    payout_request.provider_withdrawal_id = str(withdrawal_id) if withdrawal_id else None
    payout_request.tx_ref = str(batch_id)
    payout_request.provider_status = 'created'
    payout_request.status = STATUS_PROCESSING
    payout_request.save()

    # 3. Verify the batch (TOTP). A verify failure is TERMINAL — never blindly
    #    retry (NOWPayments locks a batch after 10 failed attempts).
    try:
        verify_resp = client.verify_payout(batch_id)
    except NowPaymentsError as exc:
        batch.status = 'verify_failed'
        batch.raw_last_status = {'error': str(exc)}
        batch.save(update_fields=['status', 'raw_last_status'])
        payout_request.status = STATUS_FAILED
        payout_request.provider_status = 'verify_failed'
        payout_request.notes = (
            f'NOWPayments verify failed for batch {batch_id} — TERMINAL, do NOT '
            f'retry (10-attempt lockout); needs human review: {exc}')
        logger.error('Crypto req %s: verify FAILED for batch %s: %s',
                     payout_request.pk, batch_id, exc)
        return False

    batch.status = 'verified'
    batch.verified_at = timezone.now()
    batch.raw_last_status = verify_resp or {}
    batch.save(update_fields=['status', 'verified_at', 'raw_last_status'])
    payout_request.provider_status = 'verified'
    logger.info('Crypto req %s: NOWPayments batch %s created + verified (currency=%s).',
                payout_request.pk, batch_id, currency)
    return True


def _dispatch_wise(payout_request, pm) -> bool:
    from payouts.providers.wise import WiseProvider
    provider = WiseProvider()
    if not provider.is_enabled():
        logger.info('Wise disabled, skipping req %s', payout_request.pk)
        return False
    return provider.send_payout(payout_request, pm)


def _dispatch_mpesa(payout_request, pm) -> bool:
    from payouts.providers.mpesa import MpesaProvider
    provider = MpesaProvider()
    if not provider.is_enabled():
        logger.info('M-Pesa disabled, skipping req %s', payout_request.pk)
        return False
    return provider.send_payout(payout_request, pm)


def _dispatch_paypal(payout_request, pm) -> bool:
    from payouts.providers.paypal import PayPalProvider
    provider = PayPalProvider()
    if not provider.is_enabled():
        logger.info('PayPal disabled, skipping req %s', payout_request.pk)
        return False
    return provider.send_payout(payout_request, pm)


def _dispatch_paxum(payout_request, pm) -> bool:
    from payouts.providers.paxum import PaxumProvider
    provider = PaxumProvider()
    if not provider.is_enabled():
        logger.info('Paxum disabled, skipping req %s', payout_request.pk)
        return False
    return provider.send_payout(payout_request, pm)

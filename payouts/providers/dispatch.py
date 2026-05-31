"""
Dispatch a PayoutRequest to the correct provider.
Each provider is feature-flagged via env vars (blank = disabled).
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def get_crypto_provider():
    """Return the configured crypto provider instance."""
    provider_name = getattr(settings, 'CRYPTO_PAYOUT_PROVIDER', 'nowpayments')
    if provider_name == 'self_custodial':
        from payouts.crypto.self_custodial import SelfCustodialProvider
        return SelfCustodialProvider()
    from payouts.crypto.nowpayments import NowPaymentsProvider
    return NowPaymentsProvider()


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
    from payouts.models import STATUS_PROCESSING, STATUS_FAILED
    provider = get_crypto_provider()
    if not provider.is_enabled():
        logger.info('Crypto provider disabled, skipping req %s', payout_request.pk)
        return False
    details = pm.details if pm else {}
    network = details.get('network', '')
    address = details.get('wallet_address', '')
    result = provider.send_payout(
        network=network,
        wallet_address=address,
        amount_usd=float(payout_request.amount),
        payout_request_id=payout_request.pk,
    )
    if result.success:
        payout_request.status = STATUS_PROCESSING
        payout_request.tx_ref = result.tx_hash
        return True
    payout_request.status = STATUS_FAILED
    payout_request.notes = result.error
    return False


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

r"""NOWPayments IPN (Instant Payment Notification) signature verification.

FAIL-CLOSED by construction: the only way :func:`verify_ipn_signature` returns
``True`` is a byte-for-byte HMAC-SHA512 match computed with the shared
``NOWPAYMENTS_IPN_SECRET`` over the canonicalized body. A missing secret, a
missing/empty signature header, an unparseable body, or any mismatch all return
``False``. There is no path that trusts the payload before the signature passes.

Canonicalization (must match NOWPayments' server side EXACTLY)
-------------------------------------------------------------
NOWPayments signs the *sorted* JSON object, not the raw bytes we receive. Their
own reference implementations (the official WooCommerce plugin and the IPN
help-doc) do, in PHP::

    $data = json_decode($request_json, true);
    ksort($data);                       // the IPN tutorial uses a *recursive* tksort()
    $sorted = json_encode($data);       // PHP default flags
    $sig = hash_hmac('sha512', $sorted, $ipn_secret);

To reproduce PHP's ``json_encode`` default output in Python we must match three
things:

  1. **Recursive key sort.** ``json.dumps(sort_keys=True)`` sorts keys at every
     nesting level, matching the documented recursive ``tksort``.
  2. **Compact separators.** PHP emits no spaces: ``separators=(',', ':')``.
  3. **Escaping.** PHP escapes non-ASCII as ``\uXXXX`` (``ensure_ascii=True``
     gives us that) AND escapes every forward slash as ``\/`` (e.g. inside an
     ``ipn_callback_url``). Python's ``json.dumps`` does NOT escape slashes, so we
     post-process to add the ``\/`` escaping. ``/`` only ever appears inside JSON
     string values, so a blanket replace is safe and faithful to ``json_encode``.

A canonicalization that diverged from NOWPayments' would only ever reject a
genuine IPN (fail-closed) — it can never accept a forgery, because a forger
cannot produce a valid HMAC without the secret. We still match the documented
scheme precisely so genuine IPNs are not bounced.
"""
import hashlib
import hmac
import json
import logging
from typing import Union

logger = logging.getLogger(__name__)


def canonical_json(data) -> str:
    """Serialize ``data`` exactly as NOWPayments' PHP ``json_encode`` would.

    Recursive key sort + compact separators + ``\\uXXXX`` non-ASCII escaping +
    forward-slash escaping (``/`` -> ``\\/``). This string is what gets HMAC'd.
    """
    serialized = json.dumps(
        data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    # PHP json_encode (no JSON_UNESCAPED_SLASHES) escapes every forward slash.
    return serialized.replace('/', '\\/')


def verify_ipn_signature(raw_body: Union[bytes, str], signature: str,
                         secret: str) -> bool:
    """Return ``True`` only when ``signature`` is a valid NOWPayments IPN HMAC.

    ``raw_body`` is the EXACT request body received (bytes preferred). ``signature``
    is the ``x-nowpayments-sig`` header value. ``secret`` is ``NOWPAYMENTS_IPN_SECRET``.

    Fail-closed on every error: no secret, no signature, non-JSON body, or mismatch.
    Uses a constant-time compare (NOT ``==`` — NOWPayments' own WooCommerce sample
    uses a loose ``==``, which we deliberately do not replicate).
    """
    if not secret or not signature:
        return False
    if isinstance(raw_body, bytes):
        try:
            raw_body = raw_body.decode('utf-8')
        except UnicodeDecodeError:
            return False
    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError):
        return False

    expected = hmac.new(
        secret.encode('utf-8'),
        canonical_json(data).encode('utf-8'),
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

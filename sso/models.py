"""Audit + single-use state for Track B autologin.

Two tables, because they answer different questions and have different
lifetimes:

* ``AutologinToken`` is the nonce ledger. One row per issued token; redemption
  burns it. Single-use is enforced by an atomic
  ``UPDATE ... SET redeemed_at = now() WHERE nonce = ? AND redeemed_at IS NULL``
  — Postgres serialises the row write, so of two concurrent redemptions exactly
  one sees rowcount 1 and wins. That is why the burn lives in the database and
  not only in a cache: a cache eviction would silently make a single-use token
  replayable.

* ``AutologinAttempt`` is the security log. It records EVERY redemption
  attempt, not just successful ones. Expired, replayed, wrong-tenant and
  tampered attempts are the events worth having; a log that only contains
  successes is blind to exactly the traffic you would want to investigate.

Neither table ever stores a token. ``token_hash`` is sha256 of the token
string, which is enough to correlate an issuance with its redemption but
useless to an attacker who reads the table — the token is a bearer credential,
and holding it is being logged in.
"""
from django.conf import settings
from django.db import models


class AutologinToken(models.Model):
    """One issued autologin token. The nonce is the thing that gets burned."""

    nonce = models.CharField(max_length=64, unique=True, db_index=True)
    token_hash = models.CharField(
        max_length=64,
        help_text='sha256 of the token string. Never the token itself.',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='autologin_tokens',
    )
    scope = models.CharField(
        max_length=64,
        help_text='The landing scope the token is bound to. Nothing else is bound.',
    )

    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    issued_ip = models.GenericIPAddressField(null=True, blank=True)
    issued_user_agent = models.CharField(max_length=300, blank=True, default='')
    expires_at = models.DateTimeField(
        help_text='Denormalised from the signed token so an operator can read '
                  'expiry without holding the credential.',
    )

    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_ip = models.GenericIPAddressField(null=True, blank=True)
    redeemed_user_agent = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ('-issued_at',)

    def __str__(self):
        state = 'redeemed' if self.redeemed_at else 'unredeemed'
        return f'autologin {self.nonce[:8]}… for {self.user_id} ({state})'


class AutologinAttempt(models.Model):
    """Every redemption attempt and how it ended."""

    OUTCOME_REDEEMED = 'redeemed'
    OUTCOME_EXPIRED = 'expired'
    OUTCOME_ALREADY_USED = 'already_used'
    OUTCOME_TAMPERED = 'tampered'
    OUTCOME_FUTURE_DATED = 'future_dated'
    OUTCOME_UNKNOWN_NONCE = 'unknown_nonce'
    OUTCOME_USER_UNUSABLE = 'user_unusable'
    OUTCOME_RATE_LIMITED = 'rate_limited'
    OUTCOME_DISABLED = 'disabled'
    OUTCOME_STORE_UNAVAILABLE = 'store_unavailable'
    OUTCOME_CHOICES = [
        (OUTCOME_REDEEMED, 'Redeemed'),
        (OUTCOME_EXPIRED, 'Expired'),
        (OUTCOME_ALREADY_USED, 'Already used (replay)'),
        (OUTCOME_TAMPERED, 'Bad signature / tampered'),
        (OUTCOME_FUTURE_DATED, 'Future-dated beyond tolerance'),
        (OUTCOME_UNKNOWN_NONCE, 'No issuance record for this nonce'),
        (OUTCOME_USER_UNUSABLE, 'Bound user missing or inactive'),
        (OUTCOME_RATE_LIMITED, 'Rate limited'),
        (OUTCOME_DISABLED, 'Feature disabled'),
        (OUTCOME_STORE_UNAVAILABLE, 'Nonce/rate store unavailable'),
    ]

    # Null for a tampered token: we could not establish which user it claimed
    # without trusting an unverified payload, and we will not.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='autologin_attempts',
    )
    token = models.ForeignKey(
        AutologinToken, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attempts',
    )
    token_hash = models.CharField(max_length=64, blank=True, default='')
    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES, db_index=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ('-attempted_at',)

    def __str__(self):
        return f'{self.outcome} @ {self.attempted_at:%Y-%m-%d %H:%M:%S}'

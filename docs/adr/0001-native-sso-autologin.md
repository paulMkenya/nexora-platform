# ADR 0001 — Native SSO autologin (Track B)

**Status:** Accepted, shipped disabled
**Date:** 2026-08-05
**Decider:** Paul

## Context

"Autologin" means two different things in crypto/forex lead distribution, and
the discovery pass separated them:

* **Track A — pass-through.** A buyer/broker CRM returns a login URL when we
  POST a lead, dropping the newly-registered consumer into their client area
  with no password. We capture and re-expose it.
* **Track B — native SSO.** A signed link that logs a user directly into *our*
  affiliate dashboard, for partners embedding us in their own portal.

Track A was deferred. Track B is what this ADR covers.

## The justification is thin, and that is recorded deliberately

**This was built ahead of demand. Nothing consumes it.**

Discovery found no partner embedding our dashboard and no request for native
SSO. ChainPulse — the integrator whose questions prompted the work — asked
about autologin in the Track A sense (buyer → affiliate), not this one.

It was built anyway, by decision, on the reasoning that integrators keep asking
and the capability is table stakes. That is a legitimate call, but it means the
usual signal that a feature works — someone using it — is absent, and will stay
absent until a partner arrives.

**If nothing consumes this within a reasonable window, delete it. Do not leave
it dormant.** Dormant auth code is the worst of both worlds: it carries the full
blast radius of a login path while receiving none of the scrutiny that a used
one gets. The flag makes deletion cheap; take that option rather than letting it
age.

## Decisions

### Off by default, and "off" means inert

One flag, `SSO_AUTOLOGIN_ENABLED`, defaulting to `False` **in code** — an absent
environment variable means off, never on. While off:

* the endpoint returns 404 (never 403, which would confirm the feature exists);
* `issue_token()` raises, so no path can mint one — management commands, admin
  and test helpers included;
* the middleware does not attach `request.is_autologin_session` at all (absent,
  not `False`, so nothing downstream can branch on a flag that exists only
  because the code is loaded);
* nothing appears in the generated integrator doc.

Each of those has its own test. An early version built `urlpatterns`
conditionally on the flag; that read settings at *import* time, so the routing
table could not change without a restart and could not be exercised in a test.
A security flag whose "off" state is untestable is not a state you can trust, so
the route is always registered and the view decides per request.

### Fail closed on dependency loss

Redis backs the rate limiter. If it is unreachable, issuance **and** redemption
raise rather than degrading to an in-memory or no-op path. An unenforceable
single-use guarantee is worse than an outage: it silently turns a one-shot
credential into a replayable one.

### Single-use in the database, not the cache

The nonce is burned with an atomic
`UPDATE … SET redeemed_at = now() WHERE nonce = ? AND redeemed_at IS NULL`.
Postgres serialises the row write, so of N concurrent redemptions exactly one
sees rowcount 1. This lives in the database rather than only in a cache because
a cache eviction would silently make a single-use token replayable. The
concurrent case is tested with real threads on separate connections.

### Expiry is checked twice

`signing.loads(max_age=…)` catches a token that is too **old**. It does not
catch one that is **future-dated** — age goes negative and the check passes — so
a signer with a skewed clock, or a second host sharing `SECRET_KEY`, could mint
something that outlives its TTL. The payload therefore carries its own `iat`,
validated against a small tolerance.

TTL defaults to **120 seconds** with a hard **600-second ceiling** enforced in
code. Configuration above the ceiling is clamped and logged, not honoured.

### The payload carries nothing but what it must

`django.core.signing` is **signed, not encrypted** — anyone holding the token
can read the payload. It contains exactly: bound user id, landing scope, nonce,
`iat`. No PII, no email, no brand detail. Asserted by test.

### Audit records failures, not just successes

Every redemption attempt is written, with its outcome: redeemed, expired,
already-used, tampered, future-dated, unknown-nonce, rate-limited,
store-unavailable. Only logging successes produces an audit trail blind to
exactly the traffic worth investigating.

Neither table ever stores a token — only its sha256, which is enough to
correlate an issuance with a redemption and useless to someone reading the
table.

### Structured logs, not a metrics pipeline

The spec asked for a metric on redemption failures by reason. There is no
statsd, Prometheus or Sentry integration in this codebase, so outcomes are
emitted as structured log lines with an outcome label rather than pretending a
metrics pipeline exists. Wire it to a real one when one exists.

### The sensitive-action guard was renamed, not silently broadened

`block_when_impersonating` became **`block_when_not_fully_authed`**, with the old
name kept as a thin deprecated alias so the ~19 existing call sites needed no
edit.

The rename matters more than the mechanism. Leaving the old name primary is the
failure mode worth avoiding: the next person reads "impersonating", assumes that
is the whole rule, and reasons wrongly about whether a sensitive endpoint is
covered. The canonical name states the actual rule — this session is not a full,
first-party login — and adding a third restricted session type is one entry in
`_RESTRICTIONS`, after which every already-decorated endpoint is covered.

A census test enumerates the protected endpoints in both directions: a new
sensitive endpoint without the decorator fails CI, and a guarded endpoint
missing from the census fails too, so the list cannot rot.

**Known gap, recorded rather than papered over:** the brief listed *password
change* and *email change* among actions to block. Neither endpoint exists in
this codebase — there is no authenticated password- or email-change view for
affiliates, only the unauthenticated password-*reset* flow, which requires inbox
access an autologin holder does not have and so is not an escalation path. If
either is added it will fail the census until decorated.

## What a partner integration must provide

Nothing yet — there is no consumer. When one arrives, the open questions are:
which landing scopes beyond `dashboard` are needed, whether issuance should be
API-exposed or operator-driven, and whether per-partner rate limits differ from
the global default.

## Consequences

* A bearer-credential login path exists in the codebase, disabled. It logs
  loudly at WARNING on every boot when enabled, with the configured TTL.
* Two new tables, in their own migration.
* The sensitive-action guard now has one canonical name and two restriction
  types; adding a third is a one-line change plus a census update.

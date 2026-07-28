# leadgen — lead capture + buyer injection

Captures consumer leads from two intake channels and routes them out to
configured lead-buying partners. Adding a new buyer is meant to be
**config only** — a new `LeadBuyer` row, no code — as long as the buyer's
API follows the common REST + API-key + JSON leads/batch shape described
below. `op-brandy.com` is the first configured buyer and doubles as the
reference example for every field in this doc.

## How a lead flows through the system

```
                    ┌─────────────────────┐
  Affiliate's own    │  POST /api/leads/    │
  systems ─────────► │  submit (API key)    │──┐
                    └─────────────────────┘  │
                                              ▼
  FB/Google ads ──► Nexora-hosted        ┌─────────┐      ┌──────────────┐      buyer's
  landing page      /l/<offer_id>/ ────► │  Lead   │ ───► │ LeadInjection │ ───► own API
                    (public, honeypot +  │ (status:│      │ (audit trail, │      (op-brandy,
                     rate-limited)       │  new)   │      │  retry/backoff)│      etc.)
                                          └─────────┘      └──────────────┘
```

1. **Intake** — a `Lead` row is created either by an affiliate hitting the
   inbound API (`intake_channel=affiliate_api`) or by a consumer submitting
   the public capture form for one of your own Offers
   (`intake_channel=landing_page`). Right after creation, a best-effort
   `tasks.geolocate_lead` task fires to fill in `country_iso2` from the
   captured IP (see "Geolocation" below).
2. **Routing** — `tasks.resolve_buyer_for_lead()` picks the lead's brand's
   active `LeadBuyer`, falling back to a platform-wide one (`brand=None`).
3. **Injection** — every "send this lead to that buyer" path funnels through
   one shared primitive, `services.start_injection(lead, buyer, *,
   synchronous)`, which creates the `LeadInjection` row and either runs
   `inject_lead_task` inline (`synchronous=True` — an admin/affiliate
   clicking "Inject" and waiting for the result) or queues it via Celery
   `.delay()` (`synchronous=False` — auto-inject on capture, or the
   management command below). Every attempt — success, buyer-side
   rejection, transport failure, retry — is recorded on the `LeadInjection`
   row; nothing is silent.
   - **Automatic**: `tasks.maybe_auto_inject()` runs this on every new lead,
     but only sends anything if a buyer is resolved AND that buyer's
     `auto_inject` is `True` — off by default for every new buyer.
   - **Manual, one at a time or in bulk**: three UI surfaces let an admin or
     affiliate pick specific leads and a buyer, click Inject, and see an
     immediate delivered/duplicate/failed result — the Django admin bulk
     action (`/admin/leadgen/lead/`), the affiliate's own "My Leads" page
     (`/partner/leads/`, restricted server-side to leads they submitted),
     and the operator dashboard's embedded "Consumer Leads" section
     (`/admin/dashboard/`, brand-scoped). Clicking a lead's status badge on
     any of these expands the buyer's response, attempts, and failure
     reason inline.
4. **Manual/scheduled bulk injection** — leads that have no buyer configured
   yet, or a buyer with `auto_inject=False`, sit in `status=new` until you
   run `python manage.py inject_pending_leads [--buyer <slug>] [--limit N]`
   (queues via Celery, same as auto-inject — for a scheduled/cron pass
   rather than a UI click).
5. **Status sync** — a periodic Celery Beat task (`tasks.sync_buyer_statuses`,
   every 30 min) pulls each buyer's *own* free-text status for every
   delivered lead — "New", "Deposit", "Did not pick call", "Asked for
   followup", whatever their CRM tracks — into `Lead.buyer_status` /
   `LeadInjection.buyer_status`, shown as the "Lead Deposit Status" column
   everywhere leads are listed. When a buyer reports `deposit=True`,
   `Lead.status` flips to `deposit` the same way a fresh delivery would.
   This same call is also where `country_iso2` gets backfilled for any lead
   geolocation didn't already resolve (see below) — the buyer derives it
   from the phone number on their side, at no extra cost to us.

## Adding buyer #2 (or #3, #4, ...) from the template

If the new buyer's API looks like op-brandy's — REST, an API key in a
header/query string/bearer token, JSON bodies, a single + optional batch
upload endpoint, an `addedLeads`/`failedToAddLeads`-shaped response (or
close enough) — **you do not need to write any Python.** Just create a
`LeadBuyer` row, either in `/admin/leadgen/leadbuyer/add/` or via the shell:

```python
from leadgen.models import LeadBuyer

buyer = LeadBuyer.objects.create(
    brand=None,                       # or a specific Brand for a brand-scoped buyer
    name='New Buyer Inc',
    slug='new-buyer',
    is_active=True,
    auto_inject=False,                # leave OFF until you've verified a manual injection works
    base_url='https://api.newbuyer.example',
    auth_type=LeadBuyer.AUTH_API_KEY_QUERY,   # or AUTH_API_KEY_HEADER / AUTH_BEARER
    auth_param_name='apiKey',                 # the query param or header name they expect
    single_endpoint_path='/v1/leads',
    batch_endpoint_path='/v1/leads/batch',    # blank if they don't support batch
    fetch_endpoint_path='/v1/leads',          # also used for the status/deposit sync (see below)
    batch_max_size=1,                         # >1 enables inject_batch(); 1 disables it
    rate_limit_burst=60,              # from THEIR documented rate-limit policy, not a guess
    rate_limit_refill_tokens=5,
    rate_limit_refill_seconds=2,
    field_mapping={
        # our field name -> their field name. Only fields present here are
        # sent; omit a field to fall back to sending it under our own name.
        'firstname': 'FirstName',
        'lastname': 'LastName',
        'email': 'Email',
        'phone': 'Phone',
        'vertical': 'Campaign',
        'source_id': 'ExternalId',
        # NOTE: 'deposit' is never sent outbound — see build_payload() in
        # connectors.py. Deposit/status only ever flows INBOUND, via the
        # periodic tasks.sync_buyer_statuses (see "Injection" above).
    },
)
buyer.set_api_key('the-real-secret-from-their-docs')  # encrypted at rest, never logged
buyer.save(update_fields=['api_key_encrypted'])
```

Then:
1. Run `python manage.py inject_pending_leads --buyer new-buyer --limit 1`
   against one real lead and check the `LeadInjection` row it created in
   `/admin/leadgen/leadinjection/` — `status`, `response_payload`, and
   `external_id` tell you immediately whether the field mapping and auth
   are right.
2. Once you're confident, flip `auto_inject = True` on the buyer (admin or
   shell) — from then on, every new lead routed to it injects automatically.

### When you need actual code, not just config

Only subclass `LeadBuyerConnector` (in `connectors.py`) when the buyer's API
is a genuinely different shape — a different envelope for
success/duplicate/failure, XML/SOAP instead of JSON, signed-request auth,
etc. Override `build_payload()` and/or `parse_injection_result()`; leave
`_request()` (rate limiting, timeouts, auth injection, error sanitization)
alone unless the transport itself differs.

## The op-brandy.com config (reference example)

Already seeded as the `op-brandy` `LeadBuyer` row (platform-wide,
`auto_inject=False` — turn it on once you've smoke-tested a real
injection). Its shape, for reference when wiring up a similar buyer:

| LeadBuyer field | Value |
|---|---|
| `base_url` | `https://api.op-brandy.com` |
| `auth_type` | `AUTH_API_KEY_QUERY` |
| `auth_param_name` | `apiKey` |
| `single_endpoint_path` | `/public/v1/leads` |
| `batch_endpoint_path` | `/public/v1/leads/batch` |
| `fetch_endpoint_path` | `/public/v1/leads` |
| `rate_limit_burst` / `refill_tokens` / `refill_seconds` | `60` / `5` / `2` (their documented policy: 60 burst, 2.5 req/s sustained) |
| `field_mapping` | `firstname→FirstName, lastname→Lastname, email→Email, phone→PhoneNumber, vertical→Affilate (sic), source_id→SourceId` |

Its response envelope (`{"addedLeads": [...], "failedToAddLeads": [...]}`,
with `failureReason: "duplicate"` for dupes) is exactly what
`LeadBuyerConnector.parse_injection_result()` defaults to, which is why no
buyer-specific subclass was needed.

The API key itself is **not** in this doc, git, or any log line — it's only
ever readable via `buyer.get_api_key()` (Fernet-decrypted, same helper
`nexora/crypto.py` used by `Brand.smtp_password_encrypted`), and only
`nexora/crypto.py`'s `SECRET_KEY`-derived Fernet key can decrypt it.

## Two intake channels, side by side

| | Affiliate API | Landing page |
|---|---|---|
| Endpoint | `POST /api/leads/submit` (+`/batch`) | `GET`/`POST /l/<offer_id>/` |
| Auth | `Authorization: ApiKey <secret>` (affiliate's own `public_api.APIKey`) | none — public |
| Abuse control | `APIKeyThrottle` (per-key hourly limit) | honeypot field + per-IP hourly cap (fails open if cache is down) |
| `Lead.affiliate` | the submitting affiliate | `null` — the ad platform drove the click, not a Nexora affiliate |
| `Lead.intake_channel` | `affiliate_api` | `landing_page` |

Both paths validate through the same `LeadSubmitSerializer` and both call
`tasks.geolocate_lead()` + `tasks.maybe_auto_inject()` on creation — the
buyer-routing/injection logic is identical regardless of where the lead
came from.

## Geolocation (`Lead.country_iso2`)

Not set at intake — filled in by whichever of these lands first, and never
overwrites an existing value:

1. `tasks.geolocate_lead` — fired right after every lead is created, looks
   up the captured IP via `ext.ipstack.api` (requires `settings.IPSTACK_TOKEN`
   — **currently unset**, so this path is wired but inert until a real token
   is added to `.env.prod`). Never retries; a missed lookup isn't worth
   spamming ipstack over. For affiliate-API leads specifically, the captured
   IP is the *affiliate's own submitting system*, not necessarily the
   consumer's — treat that channel's geolocation as a best-effort fallback.
2. `tasks.sync_buyer_statuses` — a free byproduct of the periodic status
   sync (see "Injection" above): the buyer derives `countryIso2` from the
   phone number on their side and returns it alongside status/deposit for
   every delivered lead, at no extra API cost.

## Lead distribution / routing (in progress)

Nexora is moving from "one lead, one destination" to a broker/router model —
building against `Nexora_Lead_Distribution_Build_Guide.md`, phase by phase,
each with its own gate/sign-off before the next starts. **Nothing described
here is wired to auto-send yet** — everything below is a complete, tested
capability, deliberately not connected to any live capture/intake path.
That connection is a later, explicit step.

**Phase 1 — routing rules** (`routing.py`): `RoutingRule` is a brand-scoped
row matching leads on `offer` / `country_iso2` / `affiliate` / `vertical` /
`source_channel` (each blank/null is a wildcard). `resolve_buyer_chain(lead)`
is the pure resolver — given a lead, it returns the ordered, deduplicated
list of active buyers to attempt from its brand's active matching rules. No
side effects, no network. A new rule's `is_active` defaults to `False`, same
kill-switch posture as `LeadBuyer.auto_inject`.

**Phase 2 — failover** (`failover.py`): `advance_chain(lead_id)` walks a
resolved chain, starting the next untried buyer the moment the current one
reaches a **terminal** outcome (buyer-side rejection — duplicate, invalid
geo, cap hit — or its own transient retries exhausted). A **transient**
failure (timeout, 5xx, connection error) still within its retry budget
never advances the chain — `tasks.inject_lead_task`'s existing per-buyer
Celery backoff keeps retrying the *same* buyer, exactly as it always did.
`LeadInjection.chain_managed` is the opt-in signal: only injections created
by `advance_chain` trigger this behavior on a terminal outcome — every
deliberate single-buyer injection (Django admin, affiliate My Leads, the
dashboard, auto-inject, the management command) is completely unaffected,
`chain_managed=False` by default. When every buyer in the chain has been
tried with no acceptance (or the chain resolved empty), the lead settles
into `Lead.STATUS_UNROUTED`. Idempotent: `advance_chain` always re-derives
"what's next" from the actual `LeadInjection` rows rather than a separate
cursor, so calling it repeatedly (or on an already-accepted lead) never
double-sends.

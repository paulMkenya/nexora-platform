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

As of Phase 4 (the Box Registry — see below), platform-level API shape and
brand-specific identity are two separate rows, so onboarding splits into two
cases:

**Case A — a brand on a platform someone's already onboarded** (e.g. a
second brand also wants to sell into op-brandy.com). No new `BoxType`
needed — just create a `LeadBuyer` instance pointing at the existing one:

```python
from leadgen.models import BoxType, LeadBuyer

box_type = BoxType.objects.get(slug='op-brandy-v1')
buyer = LeadBuyer.objects.create(
    brand=my_brand,                   # or None for a platform-wide buyer
    box_type=box_type,
    name='op-brandy.com (Brand X)',
    slug='op-brandy-brand-x',
    is_active=True,
    auto_inject=False,                # leave OFF until you've verified a manual injection works
    base_url='https://api.op-brandy.com',
    field_mapping={},                 # only set keys here to OVERRIDE box_type.default_field_mapping
)
buyer.set_api_key('the-real-secret-from-their-docs')  # encrypted at rest, never logged
buyer.save(update_fields=['api_key_encrypted'])
```

**Case B — a genuinely new platform.** Create the `BoxType` once (its
`connector_class` stays the default `leadgen.connectors.LeadBuyerConnector`
unless the API shape needs actual code — see below), then create the
`LeadBuyer` instance exactly as in Case A:

```python
from leadgen.models import BoxType, LeadBuyer

box_type = BoxType.objects.create(
    name='New Buyer Inc',
    slug='new-buyer-inc-v1',
    auth_type=BoxType.AUTH_API_KEY_QUERY,     # or AUTH_API_KEY_HEADER / AUTH_BEARER
    auth_param_name='apiKey',                 # the query param or header name they expect
    single_endpoint_path='/v1/leads',
    batch_endpoint_path='/v1/leads/batch',    # blank if they don't support batch
    fetch_endpoint_path='/v1/leads',          # also used for the status/deposit sync (see below)
    batch_max_size=1,                         # >1 enables inject_batch(); 1 disables it
    rate_limit_burst=60,              # from THEIR documented rate-limit policy, not a guess
    rate_limit_refill_tokens=5,
    rate_limit_refill_seconds=2,
    default_field_mapping={
        # our field name -> their field name. Only fields present here are
        # sent; omit a field to fall back to sending it under our own name.
        # Lives on the BoxType because it's identical for every brand on
        # this platform — a LeadBuyer instance only needs field_mapping
        # entries where ITS naming differs from the template.
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
# then create the LeadBuyer instance as in Case A, pointing box_type at this row
```

Both cases finish the same way — and as of Phase 5, neither needs shell
access for the common case:

1. Open the buyer in the Distribution console
   (`/admin/distribution/buyers/<pk>/edit/`) and click **Test Connection**.
   This sends one synthetic, obviously-fake lead (`nexora-test-connection@
   example.invalid`) through the buyer's real connector — the exact same
   code path a real lead uses — and shows the raw request payload and the
   buyer's raw response (or error) right there on the page. Nothing is
   saved to the Leads console, no `Lead`/`LeadInjection` row is created —
   it's a pure connectivity check. This is enough to confirm auth, the
   endpoint, and field mapping are all correct before anything real is at
   stake. (The console's **Save** button always tests the currently SAVED
   config, not in-progress edits — save first, then test.)
2. For a check against a *real* lead already in the system instead of a
   synthetic one, `python manage.py inject_pending_leads --buyer <slug>
   --limit 1` still works exactly as before, creating a real
   `LeadInjection` row in `/admin/leadgen/leadinjection/`.
3. Once you're confident, flip `auto_inject = True` on the buyer (admin,
   shell, or the console form) — from then on, every new lead routed to it
   injects automatically.

### When you need actual code, not just config

Only subclass `LeadBuyerConnector` (in `connectors.py`) when the buyer's API
is a genuinely different shape — a different envelope for
success/duplicate/failure, XML/SOAP instead of JSON, signed-request auth,
etc. Override `build_payload()` and/or `parse_injection_result()`; leave
`_request()` (rate limiting, timeouts, auth injection, error sanitization)
alone unless the transport itself differs. Point the new `BoxType`'s
`connector_class` at your subclass's dotted path (e.g.
`'leadgen.connectors.SomeWeirdBuyerConnector'`) — resolved via
`get_connector()` at call time, see "Phase 4 — the Box Registry" below.

## The op-brandy.com config (reference example)

Already seeded as `BoxType` #1 (`slug='op-brandy-v1'`), with one `LeadBuyer`
instance (`slug='op-brandy'`, platform-wide, `auto_inject=False` — turn it
on once you've smoke-tested a real injection). Its shape, for reference
when wiring up a similar buyer:

| BoxType field | Value |
|---|---|
| `auth_type` | `AUTH_API_KEY_QUERY` |
| `auth_param_name` | `apiKey` |
| `single_endpoint_path` | `/public/v1/leads` |
| `batch_endpoint_path` | `/public/v1/leads/batch` |
| `fetch_endpoint_path` | `/public/v1/leads` |
| `rate_limit_burst` / `refill_tokens` / `refill_seconds` | `60` / `5` / `2` (their documented policy: 60 burst, 2.5 req/s sustained) |
| `default_field_mapping` | `firstname→FirstName, lastname→Lastname, email→Email, phone→PhoneNumber, vertical→Affilate (sic), source_id→SourceId` |

| LeadBuyer instance field | Value |
|---|---|
| `box_type` | the BoxType above |
| `base_url` | `https://api.op-brandy.com` |
| `field_mapping` | `{}` (no brand-specific overrides needed yet — uses the BoxType's mapping as-is) |

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

**Phase 3 — the Distribution console** (`admin_urls.py` / `admin_views.py`
/ `forms.py` / `templates/leadgen/console/`): a purpose-built surface at
`/admin/distribution/` — **Leads**, **Buyers**, **Routing Rules** — on the
shared shell, replacing the raw table that used to sit bolted under the
operator dashboard. Every view is brand-scoped exactly like the dashboard
(a superuser sees/acts across every brand; an operator only their own — a
brand-scoped operator's Buyer/Routing Rule forms lock `brand` to their own,
so they can't create a platform-wide buyer or a rule for someone else's
brand). The Leads console shows each lead's *computed* buyer chain (what
`resolve_buyer_chain` would do right now — nothing has run yet) alongside
per-lead/bulk **Route now**, which deliberately triggers `advance_chain`
(async — results appear as the worker processes them, not inline). Django
admin (`leadgen/admin.py`) stays available as the power-user fallback and
test surface; nothing there was removed.

**Phase 4 — the Box Registry** (`models.py::BoxType` / `connectors.py::get_connector`):
splits what used to be a single `LeadBuyer` row into two levels —

- **`BoxType`** — a reusable, platform-level template: everything about a
  lead-buying platform's own API that's identical no matter which brand is
  selling into it (auth scheme, endpoint paths, rate-limit policy,
  `connector_class`, `default_field_mapping`).
- **`LeadBuyer`** — now a *buyer instance*: which `BoxType` it speaks, plus
  only what varies per brand — `base_url`, the encrypted API key, and a
  `field_mapping` that's merged on top of the `BoxType`'s own
  (`get_effective_field_mapping()`, instance overrides win). Onboarding
  brand #2 (or #10) onto a platform already in the registry is a `LeadBuyer`
  row, full stop — see "Adding buyer #2" above for both cases (existing
  platform vs. a genuinely new one).

Connector class selection is **declarative**, not eval'd code:
`BoxType.connector_class` is a dotted Python path, resolved through
Django's own `django.utils.module_loading.import_string` — the same
mechanism behind `AUTHENTICATION_BACKENDS`/`STORAGES` — via
`connectors.get_connector(buyer)`. Every call site that used to construct
`LeadBuyerConnector(buyer)` directly now goes through `get_connector()`, so
a buyer on a non-default `BoxType` actually gets its own connector class.

**Migration was purely additive, no destructive schema change**: the old
per-buyer fields (`auth_type`, `single_endpoint_path`, `batch_max_size`,
the rate-limit fields, etc.) still exist as columns on `LeadBuyer` — they're
just inert now, kept as `LeadBuyer._LEGACY_FIELDS` (the single list both
`forms.py`, which excludes them from the console form entirely, and
`admin.py`, which keeps them visible-but-readonly for audit/debugging, key
off of). Nothing reads them anymore; a future cleanup pass can drop them
once every buyer has been backfilled onto a `BoxType` and Paul is
comfortable with the drop.

op-brandy.com was backfilled as `BoxType` #1 (`slug='op-brandy-v1'`) from
its live, already-working config — its `LeadBuyer` row's identity fields
(`base_url`, the encrypted API key) were untouched; only its now-legacy
platform-level fields moved to the new `BoxType` and its `field_mapping`
was cleared to `{}` (the whole mapping now lives on the `BoxType`, with the
instance free to override individual keys later if a second brand on this
same box needs different field names). Verified after backfill:
`get_effective_field_mapping()`, `supports_batch`, and `get_connector()`
all resolve identically to their pre-Phase-4 behavior — a mocked-HTTP
verification confirmed the connector still builds the exact same request
(URL, auth param, field mapping) it did before the split; the only
divergence found was the throwaway-verification-container's `SECRET_KEY`
not matching the live container's — a pre-existing, unrelated gap (see
"the API key itself is not in this doc" above), not a Phase 4 bug.

**Phase 5 — trivial buyer onboarding UI** (`buyer_form.html` /
`admin_views.buyer_test_connection` / `connectors.MAPPABLE_LEAD_FIELDS`):
the Buyer form gained two things aimed squarely at "onboard brand #2 without
touching a shell":

- **A live field-mapping override editor.** Selecting a `BoxType` shows its
  `default_field_mapping` right there on the form (updates instantly,
  client-side, as you change the dropdown — every `BoxType`'s defaults are
  fetched once on page load, no extra requests). Below it, `field_mapping`
  is no longer a raw JSON textarea to hand-edit — it's a row-per-override
  editor (our field ↔ their field name) that serializes to the same
  underlying JSON field on submit. The raw textarea still exists in the DOM
  (hidden, not removed) as the actual field the form posts, so nothing
  about how `LeadBuyerForm`/`LeadBuyer.field_mapping` works changed — this
  is presentation only.
- **A "Test Connection" button** (only shown once a buyer has been saved).
  Sends one synthetic, obviously-fake lead (`first_name='Nexora'`,
  `email='...@example.invalid'`, `source_id='test-connection-<slug>'`)
  through the buyer's *real* connector — same `get_connector()` +
  `build_payload()` + the actual HTTP call a live lead would use — and
  shows the raw request payload and the buyer's raw response (or a
  sanitized error) inline. Deliberately never creates a `Lead` or
  `LeadInjection` row, so it can't pollute the Leads console, routing
  stats, or billing — it's a connectivity/config check, not a real
  delivery. Tests the buyer's currently-*saved* configuration, not
  in-progress form edits (the endpoint ignores the POST body entirely and
  re-reads the instance from the DB) — save changes first, then test.
  Verified live against op-brandy.com's real endpoint from a throwaway
  preview container: the connector built and sent the exact expected
  payload (`FirstName`/`Lastname`/`Email`/`PhoneNumber`/`SourceId`/
  `Affilate`, matching `BoxType.default_field_mapping`) and the page
  correctly surfaced the buyer's real `401` response — proving the whole
  path works end-to-end, independent of the known, pre-existing
  throwaway-container `SECRET_KEY`/API-key gap.

`MAPPABLE_LEAD_FIELDS` (`connectors.py`) is now the single source of truth
for which our-field-name keys are meaningful in a `field_mapping` override
— both `build_payload()` and the editor's per-row dropdown read from it, so
the two can never drift apart.

**Phase 6 — source channel tightening.** This phase's guide text names two
things platform-owner judgment was needed on. Both were decided and
documented here rather than deferred, since a go-live gate shouldn't sit
blocked on a question that has a safe, conservative default:

- **Is `Lead.intake_channel` actually stamped correctly at every capture
  point?** Audited both real paths: `api_views.py::_create_lead` sets
  `intake_channel=Lead.CHANNEL_AFFILIATE_API` and
  `public_views.py::capture_lead` sets `intake_channel=Lead.CHANNEL_LANDING_PAGE`,
  both unconditionally, at the same `Lead.objects.create()` call that
  writes every other required field — there's no code path that creates a
  `Lead` without one. Nothing to fix; this was already solid going back to
  the original build.
- **`RoutingRule.source_channel` has a third `'bought'` (Bought traffic)
  choice with no intake channel that ever produces it** — the model
  anticipated a lead-buying/bulk-purchase intake path that was never
  built. Building that path (a bulk-CSV import? a dedicated broker-facing
  API? who's authorized to use it, and does it bypass affiliate
  commission/billing the way affiliate-submitted leads don't?) is a real
  product and security-surface decision, not a "tighten existing code"
  one — explicitly out of scope for autonomous judgment, left for Paul to
  scope whenever there's an actual bought-traffic source to wire up.
  What *was* addressed: the option sat in the dropdown with no
  indication it was inert, so an operator could build a routing rule
  around `source_channel='bought'` believing it was live, and that rule
  would silently never match a single lead. `RoutingRule.source_channel`
  now carries a `help_text` saying exactly that (surfaces automatically in
  both the console form and Django admin — one field definition, no
  template changes needed). No new intake path was built.
- **Does the landing page redirect anywhere after a successful capture?**
  Checked `public_views.py::capture_lead` — no, it re-renders
  `capture_form.html` in place with `submitted=True` (an inline
  "thanks" state), no `HttpResponseRedirect`. Whether a post-capture
  redirect to an advertiser's own page (e.g. for a tracking pixel a
  specific advertiser relies on) should exist depends entirely on the
  advertiser/offer's actual requirements, which nothing in this repo
  states — building one speculatively would be guessing at a live,
  revenue-facing consumer flow's requirements. Left unchanged.
  Recommendation for whenever this becomes a real requirement: an
  optional per-`Offer` `post_capture_redirect_url` field, used if set and
  falling back to today's inline "thanks" behavior otherwise — additive,
  and doesn't force every existing offer to have an opinion.

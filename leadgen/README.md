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
   (`intake_channel=landing_page`).
2. **Routing** — `tasks.resolve_buyer_for_lead()` picks the lead's brand's
   active `LeadBuyer`, falling back to a platform-wide one (`brand=None`).
3. **Injection** — if a buyer is resolved AND that buyer's `auto_inject` is
   `True`, a `LeadInjection` row is created and `inject_lead_task` is
   enqueued on Celery. Every attempt — success, buyer-side rejection,
   transport failure, retry — is recorded on that row; nothing is silent.
4. **Manual/scheduled injection** — leads that have no buyer configured yet,
   or a buyer with `auto_inject=False`, sit in `status=new` until you run
   `python manage.py inject_pending_leads [--buyer <slug>] [--limit N]`.

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
    fetch_endpoint_path='/v1/leads',
    deposits_endpoint_path='',                # blank if not applicable
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
        # connectors.py. Deposit status only ever flows INBOUND, via
        # fetch_deposits() / a future deposit-sync task.
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
| `deposits_endpoint_path` | `/public/v1/leads/deposits` |
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
`tasks.maybe_auto_inject()` on creation — the buyer-routing/injection logic
is identical regardless of where the lead came from.

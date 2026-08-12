# TrackBox (Tigloo) — integration notes

Box #3, after op-brandy and Hypernet. Connector:
`leadgen.connectors.TrackBoxConnector`. Seed:
`python manage.py seed_trackbox_box`.

Vendor docs (request shapes only):
<https://intercom.help/tigloo/en/articles/9349579-trackbox-api-documentation>

First instance: **Traffix** — `https://platform.traffixworld.com`, traffic
from the affiliate **exxtraffic**.

---

## 1. The thing that makes this box different

**Every failure arrives as `HTTP 200`.** This is not in their documentation.
Verified against the live box on 2026-08-12 by POSTing to
`/api/pull/customers`:

| Request | HTTP | Body |
|---|---|---|
| no auth headers at all | `200` | `{"status": false, "message": "Cant Pull Data, please contact support with caseID: …", "code": 401}` |
| username + password, no `x-api-key` | `200` | same as above |
| username + password + junk `x-api-key` | `200` | `{"status": false, "message": "User and password doesnt match, please supply support with case ID: …", "code": 401}` |
| junk username + password + junk `x-api-key` | `200` | same as above |
| username + password + the **doc's placeholder** key `2643889w34df345676ssdas323tgc738` | `200` | same as above — byte-identical to a random invalid key |

**Their error text is misleading and has already cost time once.** "User and
password doesnt match" is what the box says when the **`x-api-key`** is
wrong, even though the username and password are correct. Do not go back to
the vendor asking about the password on the strength of that message —
check the API key first.

The generic `LeadBuyerConnector` classifies on the HTTP status line (see
`LeadBuyerError`'s table). On this box it would therefore read a flat
credentials rejection as a **success**, hand it to
`parse_injection_result()`, and record it against the **lead** as a
rejection — burning one real lead per attempt to report a configuration
error. `TrackBoxConnector._raise_for_soft_error()` restores the
classification from the body.

The response `Content-Type` is `text/html; charset=UTF-8` even though the
body is JSON. `requests`' `.json()` ignores content-type, so the base
connector parses it fine; do not "fix" this by adding a content-type check.

### How a body error maps onto the shared taxonomy

| Body | Raises | Why |
|---|---|---|
| `code` 401 / 403 | `LeadBuyerError` (**retryable**) | A property of OUR config, not of the lead. Fixable — once the key is corrected the identical lead succeeds. Cascading would walk a good lead through the whole buyer chain over a credential typo. Logged at ERROR: every lead will fail identically until a human acts. |
| message matches "no available brands", "cap full", "daily limit" | `LeadBuyerCapacityError` | Temporary by construction — see that class, and the 10 real leads its absence cost on Hypernet. |
| anything else with `status: false` | *not raised* | A verdict on **this lead**. Falls through to `parse_injection_result()`, which records the buyer's own message as the failure reason. Raising would swap a readable operator explanation for a stack trace and lose `response_payload`. |

The pull path has no `parse_injection_result()` to fall through to, so
`_pull_window()` checks for an error body itself and raises. Without that, an
auth outage during status sync would read as "this window has no rows" and
the sync would log as perfectly healthy while delivering nothing.

---

## 2. Auth — three headers

```
x-trackbox-username: <username>
x-trackbox-password: <password>
x-api-key:           <api key>
Content-Type:        application/json
```

`BoxType.auth_type` models exactly one credential, so:

- the **API key** goes through it as normal
  (`AUTH_API_KEY_HEADER` / `auth_param_name='x-api-key'`), stored in
  `LeadBuyer.api_key_encrypted`;
- the **username/password** come from
  `LeadBuyer.extra_credentials_encrypted` — a new Fernet-encrypted JSON
  column (migration `leadgen/0015`) — via
  `TrackBoxConnector.extra_auth_headers()`, a new no-op-by-default hook on
  the base connector.

They are **not** in `extra_payload_fields`: that column is plaintext and is
rendered in the operator console, so a password there would be a plaintext
credential on a page.

`extra_auth_headers()` **raises** rather than sending a half-authenticated
request. Because the box answers 200 to a bad credential, sending anyway
would produce an ordinary-looking body recorded against the lead.

### ⚠️ Open blocker: no `x-api-key`

The credentials supplied for Traffix are username `DanTVSnew`, a password,
`ai=2958839`, `ci=1`, `gi=843`. **No `x-api-key` was supplied**, and the
probe table above shows it is mandatory — without it the box answers `401`
regardless of whether the username and password are correct.

So the integration is complete and configurable, but **cannot be verified
end-to-end until Traffix supplies the API key**.

What to ask for, precisely: *the `x-api-key` value issued for the API user
`DanTVSnew` on platform.traffixworld.com*. It is a per-account secret their
side generates. It is **not** `ai`, `ci` or `gi`, and it is **not** the
placeholder printed in their public documentation — that value
(`2643889w34df345676ssdas323tgc738`) was tried against the live box on
2026-08-12 and rejected exactly like a random string.

Once it arrives, see §7.

---

## 3. Endpoints

| Purpose | Method | Path |
|---|---|---|
| Push a lead | `POST` | `/api/signup/procform` |
| Pull statuses/deposits | `POST` | `/api/pull/customers` |

Note the pull endpoint is a **POST with a JSON body**, not the base class's
GET with a query string — `fetch_leads()` is overridden accordingly. Sent as
query params, the box would ignore the date window entirely.

No batch endpoint is documented; `inject_batch()` refuses outright.

---

## 4. The signup body

Static per-buyer constants (from `LeadBuyer.extra_payload_fields`, seeded by
the management command) — these are properties of the **buyer**, not of any
lead, so nothing maps them:

| Key | Traffix value | Meaning |
|---|---|---|
| `ai` | `2958839` | affiliate id ("ask your trackbox partner") |
| `ci` | `1` | campaign id |
| `gi` | `843` | ("ask your trackbox partner") |
| `so` | `exxtraffic` | funnel/source name shown in their reports |
| `lg` | `EN` | language |

Mapped from the lead (`BoxType.default_field_mapping`):

| Ours | Theirs |
|---|---|
| `firstname` | `firstname` |
| `lastname` | `lastname` |
| `email` | `email` |
| `phone` | `phone` |
| `source_id` | `sub` |

Plus, assembled by the connector because they are outside
`MAPPABLE_LEAD_FIELDS`:

- `userip` — from `Lead.ip`
- `password` — synthesized per lead by `BrokerPasswordMixin`, stored
  encrypted on `Lead.broker_password_encrypted`, and put on the wire **only**
  in `inject_lead()`. `build_payload()` — and therefore the audit trail and
  the console — sees `[redacted]`.

`phone` is normalized to a bare international MSISDN (no `+`), matching their
own example `4407012259886`.

`vertical` is deliberately **not** mapped. Their nearest field is `so`, which
identifies the traffic source for the whole box and is agreed per-buyer. A
brand that wants the lead's vertical on TrackBox should map it to one of the
`MPC_1`…`MPC_12` free parameters via `LeadBuyer.field_mapping`.

---

## 5. What is NOT known, and how the code handles it

Their docs publish **no response schema at all**, and the credentials in hand
cannot complete an authenticated request. So every response-side key name is
a **candidate set** rather than a single known key:

- `TrackBoxConnector.EXTERNAL_ID_KEYS` — where a successful signup carries
  the id we store as `LeadInjection.external_id`.
- `TrackBoxConnector.ROW_ID_KEYS` — the same value on a pull row. (The write
  and read sides of these boxes routinely disagree about the name — on
  Hypernet the injection responds with `leadId` but the read side keys it as
  `id`, and reading the wrong one silently yields nothing while every lead
  looks absent.)
- `parse_status_sync_results()` reads status/deposit/date/country through
  `_first_present()` fallback chains.

Each one **logs loudly** when nothing matches rather than returning a silent
empty. That matters most for the external id: an empty `external_id` excludes
the lead from every future status sync
(`tasks.sync_buyer_statuses` filters `.exclude(external_id='')`), so a
deposit would never come back. The first real delivery is therefore
self-diagnosing — grep the worker log for
`no recognisable lead id` and add the real key.

A success with no recognisable id is still recorded as **delivered**, not
failed: the lead *was* accepted, and calling it failed would cascade it to a
competitor.

### Autologin URLs

Their `data` object carries autologin links — their own help centre describes
"masked" auto-login URLs plus an `autoLoginUrl` holding the real brand URL.
An autologin URL is a **bearer credential** that logs the lead straight into
the broker, and `LeadInjection.response_payload` is rendered to affiliates
(`affiliate_ui/templates/affiliate_ui/leads.html`).

`AUDIT_RESPONSE_ALLOWLIST` therefore allows `data` — which means *recurse
into it*, not *publish it* — plus the id keys, `status`, `code` and
`message`. Every other key inside `data` is redacted by default-deny, so the
autologin URL stays redacted **without this code having to know which of
their several names it arrives under**. That is precisely the property needed
when the schema is undocumented; do not replace it with a blocklist.

`message` is allowed deliberately: on a failure it is the only
operator-readable explanation the box gives, and it carries their support
`caseID`, which is what a human needs to open a ticket with them.

---

## 6. Status sync

Their pull filters on **registration date**, not on when a status changed —
the same shape of problem Hypernet has, so both now share
`DateWindowStatusSyncMixin`. Windowing on "the last hour of changes" would be
wrong: a lead that registered in March and deposits today appears in a
**March** window, never in a today window, and the sync would look healthy
while missing almost every deposit.

Instead the window is built from **our own injection timestamp**, padded by
`STATUS_SYNC_WINDOW_PAD` (48h, inherited from Hypernet's measured 18h24m
skew), with overlapping day-windows coalesced before any request goes out.

Their pagination is a 1-based **page number** against `meta.lastPage`
(Hypernet's is skip/take against a total), which is the only piece
`_pull_window()` supplies. `type: "3"` = Leads + Deposits; asking for type 4
(deposits only) would make a lead's status invisible until it converted,
which is the whole progression the sync exists to report.

Documented pull envelope:

```json
{"data": [], "meta": {"limit": 500, "count": 0, "total": 0,
                      "currentPage": 1, "lastPage": 1,
                      "prevUrl": null, "nextUrl": null}}
```

Note it carries **no `status` key** on success — which is why
`_is_soft_error()` tests for an explicitly falsy `status` key rather than a
missing one. Treating "absent" as failure would make every healthy pull look
like an outage.

---

## 7. Onboarding checklist

```bash
# 1. BoxType only — safe, no credentials involved
python manage.py seed_trackbox_box

# 2. The buyer. All three secrets come from the environment, never argv
#    (argv is visible in `ps` and lands in shell history).
TRACKBOX_API_KEY=...        \
TRACKBOX_USERNAME=DanTVSnew \
TRACKBOX_PASSWORD=...       \
python manage.py seed_trackbox_box \
    --buyer --brand <brand-slug> \
    --base-url https://platform.traffixworld.com \
    --ai 2958839 --ci 1 --gi 843 --so exxtraffic
```

The buyer is created with `auto_inject=False`. **Leave it off** until a
manual test injection comes back `status: true` and the `LeadInjection` row
reads `delivered`.

On this box that gate matters more than usual: a "successful" HTTP call
proves nothing, because it answers `200` when it rejects your credentials.
Read the stored `response_payload`, not the HTTP status.

Then:

1. Check the worker log for `no recognisable lead id`. If present, add the
   real key to `EXTERNAL_ID_KEYS` and re-run.
2. Confirm the first status sync returns rows; if every lead logs as absent,
   the row id key is wrong — add it to `ROW_ID_KEYS`.
3. Fill in `DEFAULT_STATUS_MAPPING` in `seed_trackbox_box.py` as their real
   status strings appear. Unmapped ones are **not** silently dropped — they
   raise `Lead.canonical_status_needs_review` (Affiliate Inbound API spec
   §3.2), which is how the remaining values get discovered.
4. Only then flip `auto_inject=True`.

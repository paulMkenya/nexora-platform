# TrackBox (Tigloo) — integration notes

Box #3, after op-brandy and Hypernet. Connector:
`leadgen.connectors.TrackBoxConnector`. Seed:
`python manage.py seed_trackbox_box`.

Vendor docs (request shapes only):
<https://intercom.help/tigloo/en/articles/9349579-trackbox-api-documentation>

First instance: **Traffix World** — `https://platform.traffixworld.com`, traffic
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

### ⚠️ The two endpoints do NOT authenticate the same way

Established by a live end-to-end injection on 2026-08-12, using the username
and password plus the **placeholder** key from their public docs:

| Endpoint | Result with an invalid `x-api-key` |
|---|---|
| `POST /api/pull/customers` | **rejected** — `code 401` |
| `POST /api/signup/procform` | **ACCEPTED** — `status: true`, a real customer created |

So the push path either does not validate `x-api-key` at all or validates it
differently. Nothing in their documentation says this, and it has a sharp
operational consequence:

> **We can deliver leads to this box today, but we cannot read their statuses
> back.** Status sync runs against the pull endpoint, which still 401s. A lead
> delivered now would never receive a status or a deposit — no FTD would ever
> return, so nothing would bill.

Treat that as the reason to keep `auto_inject=False` until the real key
arrives, not merely as a nice-to-have. Delivering untrackable leads is worse
than delivering none.

A single test lead (`Nexora Testlead / nexora.testlead@example.com`,
`+254700000000`) was created on Traffix World during this verification. Their side
should be asked to remove it.

### ⚠️ Open blocker: no `x-api-key`

The credentials supplied for Traffix World are username `DanTVSnew`, a password,
`ai=2958839`, `ci=1`, `gi=843`. **No valid `x-api-key` was supplied.**

Pushing leads works without it (see above). **Status sync does not**, so the
integration cannot be run in production until Traffix World supplies the key —
otherwise we deliver leads whose deposits never come back.

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

| Key | Traffix World value | Meaning |
|---|---|---|
| `ai` | `2958839` | affiliate id ("ask your trackbox partner") |
| `ci` | `1` | campaign id |
| `gi` | `843` | ("ask your trackbox partner") |
| `so` | `exxtraffic` | funnel/source name shown in their reports |
| `lg` | `EN` | language |

`so` and `lg` are *defaults*, not fixed values — a lead that carries its own
funnel or language overrides them per lead (see the opt-in table below).
`ai`/`ci`/`gi` identify the buyer relationship and must never become per-lead.

Mapped from the lead (`BoxType.default_field_mapping`):

| Ours | Theirs |
|---|---|
| `firstname` | `firstname` |
| `lastname` | `lastname` |
| `email` | `email` |
| `phone` | `phone` |
| `source_id` | `sub` |

Mapped from the lead's attribution — the **opt-in** sources, emitted only
because this mapping names them and only when the lead carries a value. See
`docs/lead-attribution.md`:

| Ours | Theirs |
|---|---|
| `language` | `lg` |
| `attribution.funnel` | `so` |
| `attribution.campaign` | `campaign` |
| `attribution.medium` | `medium` |
| `attribution.term` | `term` |
| `attribution.ad` | `ad` |
| `attribution.sub1`…`sub5` | `MPC_1`…`MPC_5` |

`MPC_6`…`MPC_12` are left free for a brand to point at its own affiliate
`extra` keys via `LeadBuyer.field_mapping`.

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
now carries the lead's own funnel when it has one. A brand that wants the
lead's vertical on TrackBox should map it to one of the free `MPC_6`…`MPC_12`
parameters via `LeadBuyer.field_mapping`.

---

## 5. The signup response — captured live

Their docs publish **no response schema at all**. This is a real accepted
lead, 2026-08-12, tokens replaced:

```json
{
  "status": true,
  "data": "https://platform.traffixworld.com/u/d/<AUTOLOGIN-TOKEN>",
  "error": [],
  "addonData": {
    "status": "successful",
    "data": {
      "loginURLIsForm": false,
      "customerId": "<CUSTOMER-ID>",
      "uniqueid":   "<CUSTOMER-ID>",
      "brokerUrl":  "xxx",
      "id":         "<CUSTOMER-ID>",
      "loginURL": "https://platform.traffixworld.com/u/d/<AUTOLOGIN-TOKEN>"
    },
    "failLog": true,
    "fallbackURL": false
  },
  "originalData": []
}
```

Three things here were **not** guessable, and each broke a first
implementation:

1. **`data` is a STRING**, not an object — it is the autologin URL itself.
2. **The lead id is at `addonData.data`**, two levels down, and nowhere else.
   `customerId`, `uniqueid` and `id` all carry the same value.
3. **`error` is an empty LIST** on success, not null or absent.

### The leak this caused, and the rule that came out of it

`AUDIT_RESPONSE_ALLOWLIST` originally included `data`, on the assumption it
was a container to recurse into. Allowlisting a key means *recurse into it* —
which is safe for a container and **publishes a scalar verbatim**. The
autologin URL therefore landed unredacted on
`LeadInjection.response_payload`, which
`affiliate_ui/templates/affiliate_ui/leads.html` renders to affiliates. An
autologin URL is a bearer credential that logs the lead straight into the
broker's client area.

> **Rule for the next box: only allowlist a key you know to be a CONTAINER.
> A key whose value might be a scalar credential must be neutralised by
> SHAPE, never trusted by name.**

`sanitize_response_for_audit()` now replaces any scalar under
`SCALAR_CREDENTIAL_KEYS` before the default-deny walk begins, so a key that
is an object today and a credential tomorrow is handled correctly either
way. Pinned by `TestAutologinUrlIsNeverAudited`, including a whole-object
assertion that the token appears nowhere in the audit copy — the check that
would have caught the original leak regardless of which key carried it.

### Still-unknown keys

The signup response is now confirmed (above). The **pull-side row shape is
not** — that endpoint still 401s — so those key names remain **candidate
sets** rather than known keys:

- `TrackBoxConnector.ROW_ID_KEYS` — the lead id on a pull row. (The write and
  read sides of these boxes routinely disagree about the name: on Hypernet
  the injection responds with `leadId` while the read side keys it as `id`,
  and reading the wrong one silently yields nothing while every lead looks
  absent. TrackBox's write side offers `customerId`/`uniqueid`/`id`, all
  identical — which of those the read side uses is unverified.)
- `parse_status_sync_results()` reads status/deposit/date/country through
  `_first_present()` fallback chains.

Each **logs loudly** when nothing matches rather than returning a silent
empty, so the first successful pull is self-diagnosing.

`EXTERNAL_ID_KEYS` and `RESPONSE_ID_SCOPES` are confirmed against a real
delivery, but keep the scope list broad: the id was found ONLY at
`addonData.data`, and a search of the top level and `data` alone came back
empty. Do not narrow it on the assumption that a shallower scope is "the"
location.

A success with no recognisable id is still recorded as **delivered**, not
failed: the lead *was* accepted, and calling it failed would cascade it to a
competitor. But it is logged at ERROR, because an empty `external_id`
excludes the lead from every future status sync
(`tasks.sync_buyer_statuses` filters `.exclude(external_id='')`). Grep the
worker log for `no recognisable lead id`.

`message` is allowlisted deliberately: on a failure it is the only
operator-readable explanation the box gives, and it carries their support
`caseID`, which is what a human needs to open a ticket with them. It is not a
credential.

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

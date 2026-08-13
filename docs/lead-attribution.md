# Lead attribution — capturing and forwarding a lead's marketing detail

How a lead's *where did this come from* travels from an affiliate's system,
through Nexora, to a buyer box — and why it is shaped the way it is.

Companion to `docs/trackbox-integration.md` (the first box that needed this)
and `leadgen/README.md` (routing and delivery).

---

## 1. The problem this solves

Every buyer box in this vertical asks for the same handful of ideas under its
own names. TrackBox calls them `so`, `ad`, `term`, `campaign`, `medium` and
`MPC_1`..`MPC_12`; the next box will call them something else. Their docs mark
these *"visible in reports for statistical calculations"* — they are what a
buyer's own optimisation reporting is keyed on, and therefore part of what
decides whether that buyer keeps taking our traffic.

Before this existed, Nexora could not carry any of it:

* **Intake dropped it silently.** The inbound serializers declared
  `first_name/last_name/email/phone/vertical/source_id/offer_id/country/ip/
  user_agent/sub1..sub5` and nothing else. DRF discards undeclared keys, and
  `_create_lead` stored `raw_payload=data` — the *validated* dict — so an
  affiliate posting `campaign` or `MPC_3` got `201 Created` and no hint that
  the value had gone nowhere.
* **The mapper could not reach it.** `LeadBuyerConnector.build_payload()`
  reads `getattr(lead, attr)` over the six entries of
  `MAPPABLE_LEAD_FIELDS`, and `field_mapping` only *renames* those six. Even
  `sub1..sub5`, which intake did accept and store, had no path to a buyer.

So every lead delivered to TrackBox carried the same `so` and `lg` from the
buyer's static `extra_payload_fields`, and no campaign detail at all.

---

## 2. The shape

```
affiliate POST /api/leads/submit          Lead                  buyer payload
  language: "EN"              ------>  .language      ------>  lg          (TrackBox)
  funnel:   "crypto-quiz-v2"  ------>  .attribution   ------>  so
  campaign: "summer-crypto"       {funnel, campaign,  ------>  campaign
  sub1:     "abc"                  medium, term, ad,  ------>  MPC_1
  extra: {risk_band: "A"}          sub1..sub5, ...}   ------>  MPC_6 (if mapped)
```

### `Lead.language` is a column; attribution is a JSONField

`language` is a property of the **person**, not of the campaign that found
them: buyers route call-centre capacity on it, and it is the one enrichment
field nearly every box asks for by name. It is stable, low-cardinality and
worth querying — so it is a column.

Attribution is open-ended by nature: the set of names is whatever the next
box invents. Named columns would mean a migration per box onboarded, for data
no query filters on. So it is a flat `string -> string` JSONField, the same
shape and the same reasoning as `LeadBuyer.extra_payload_fields` one level up.

### `attribution` is not `raw_payload`

`raw_payload` is the **verbatim submission** — an audit record of what
arrived. `attribution` is the **curated, validated subset** connectors are
allowed to forward. Keeping them apart is what lets `attribution` be a stable
contract while `raw_payload` stays free to hold whatever a channel sent.

---

## 3. Intake

Canonical keys, validated by `leadgen/serializers.py`:

| Field | Where | Notes |
|---|---|---|
| `language` | `Lead.language` | ISO 639-1, optional region. Upper-cased on the way in, so `en`/`EN`/`En` are one value everywhere. |
| `funnel`, `campaign`, `medium`, `term`, `ad` | `Lead.attribution` | Named, validated, reportable. Channel-neutral names — a buyer's dialect is a *mapping* concern, never a name we adopt at intake. |
| `sub1`..`sub5` | `Lead.attribution` | Opaque affiliate passthrough; stored and returned untouched, never interpreted. Affiliate channel only. |
| `extra` | `Lead.attribution` | Free key/value escape hatch for a buyer field Nexora has no name for. Affiliate channel only. |

`extra` is bounded — at most `EXTRA_MAX_KEYS` (20) keys, keys matching
`[A-Za-z0-9][A-Za-z0-9_.-]{0,39}`, values ≤ 255 chars. It exists so a brand
can fill `MPC_6`..`MPC_12` without waiting on a migration, not as a place to
park a CRM record; an unbounded dict on this endpoint is a storage-
amplification vector. A key that collides with a named field is a `400`
rather than a silent overwrite.

Empty values are **dropped, not stored as `''`**. For several boxes an empty
string is a real value that overwrites a default, while an absent key leaves
the default alone.

### Unknown fields are reported, not rejected

`POST /api/leads/submit` now returns `ignored_fields: [...]` listing any
top-level key the contract has no field for. Advisory only — unknown keys are
still ignored, never a `400`:

* rejecting would break any affiliate already sending a field we don't read,
  and would make every future field we add a breaking change for them;
* but a **silent** drop is the failure this endpoint is least able to detect
  for the affiliate, so the names come back on the first test call.

Absent entirely on a clean submission, so nothing changes for existing
integrations.

### The landing-page channel

`leadgen/public_views.py` maps the `utm_*` convention every ad platform
already emits onto the same canonical names:

| Query string | Attribution |
|---|---|
| `utm_source` | `funnel` |
| `utm_campaign` | `campaign` |
| `utm_medium` | `medium` |
| `utm_term` | `term` |
| `utm_content` | `ad` |
| `lang` | `language` |

They arrive on the landing URL's query string and have to survive to the
POST, so `_tracking_inputs()` round-trips them through hidden inputs — the
only carrier that doesn't depend on the form's action preserving the query
string. POST wins over GET, so a re-render after a validation error keeps
what the first submission carried.

---

## 4. Forwarding — the opt-in rule

**This is the part to understand before touching it.**

`MAPPABLE_LEAD_FIELDS` is sent to **every** buyer: an entry missing from a
buyer's `field_mapping` still goes out under our own name (`_map_field`
returns the key unchanged). That is exactly why `language` and `attribution`
are **not** in it — adding them there would start putting new keys into
op-brandy's and Hypernet's live signup bodies, uninvited, on the next deploy.

The new sources are the opposite rule. `build_extra_payload()` emits a value
**only when a buyer's effective field mapping names its source explicitly**,
and under the name that mapping gives. Two source forms are understood as
mapping *keys*:

```
'language'            -> Lead.language
'attribution.<key>'   -> Lead.attribution['<key>']
```

A buyer whose mapping mentions neither sends byte-for-byte what it sent
before any of this existed. That property is what made this safe to add
underneath boxes that were already live, and it is worth a regression test
(there is one: `test_connectors.py`).

A mapped-but-absent source is omitted, never sent blank — same reasoning as
dropping empties at intake.

Placement is the connector's business, not this method's:
`build_extra_payload` returns a flat dict, `TrackBoxConnector` writes it
straight into its flat body, and `HypernetConnector` passes every key through
`_set_path()`, so a mapping targeting `profile.custom` nests correctly there.

### TrackBox's mapping

Seeded by `manage.py seed_trackbox_box` into
`BoxType.default_field_mapping`:

| Source | TrackBox field |
|---|---|
| `language` | `lg` |
| `attribution.funnel` | `so` |
| `attribution.campaign` | `campaign` |
| `attribution.medium` | `medium` |
| `attribution.term` | `term` |
| `attribution.ad` | `ad` |
| `attribution.sub1`..`sub5` | `MPC_1`..`MPC_5` |

`MPC_6`..`MPC_12` are deliberately left free: a brand points them at its own
`extra` keys (e.g. `'attribution.risk_band': 'MPC_6'`) through
`LeadBuyer.field_mapping`, which overrides the BoxType template per buyer.

`so` and `lg` remain in that buyer's static `extra_payload_fields`. Nothing
regresses for a lead with no attribution — it still gets the static values,
and a per-lead value simply wins over them, which is the precedence
`TrackBoxConnector.build_payload()` already implemented.

`ai` / `ci` / `gi` stay static. They identify the **buyer relationship**, not
the lead, and must never become per-lead.

---

## 5. The operator console

`/admin/leadgen/buyers/<id>/` builds its field-mapping editor from
`admin_views.mappable_field_sources()` — the core fields, then `language`,
then the canonical `attribution.*` keys.

Only *canonical* attribution keys can be listed: an affiliate's `extra` keys
are open-ended, so no server-side list can enumerate them. The editor
therefore keeps any source already present in a saved mapping as its own
option (`buildFieldOptions` in `buyer_form.html`). Without that, a select
whose saved value isn't in the list falls back to its first option and the
next save **silently rewrites that row to a different source** — which is how
`'attribution.risk_band': 'MPC_6'` would have quietly become
`'firstname': 'MPC_6'`.

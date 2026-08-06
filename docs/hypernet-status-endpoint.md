# Hypernet status endpoint — discovered contract

`GET {base_url}/api/external/integration/lead` — the read side of the same path
used for injection (POST).

**Source: empirical probe against the live desperados box on 2026-08-06**, not a
vendor document. We still have no written spec from Hypernet. Everything below
was observed directly; the probe was read-only (~35 GETs, nothing written on
their side). Where a claim is inferred rather than observed it says so.

Auth: header `x-api-key`, same key as injection.

## Parameters

The endpoint is **strict** — an unrecognised parameter returns `400`. That is
what makes this table trustworthy: each name below was confirmed accepted, and
the absence of an ID filter was confirmed by rejection, not by guessing.

| Param | Behaviour |
|---|---|
| `from` | Lower bound, **inclusive** (a `from` exactly equal to `createdAt` returns the row). Filters on `createdAt` — see below. Optional, works without `to`. |
| `to` | Upper bound, filters on `createdAt`. Optional, works without `from`. |
| `skip` | Offset into the matching set. |
| `take` | Page size. Valid range **1–500**. `0` → 400, `501` → 400. |
| `email` | Exact-match filter. **Supported** — returns the single matching row. |

Accepted date formats: ISO-8601 with `Z` (`2026-08-06T14:49:12.769Z`) and
date-only (`2026-08-06`). Unix epoch returns **500**, not 400 — malformed input
is not handled cleanly on their side, so always send ISO.

**There is no ID filter.** Every candidate returns 400: `id`, `ids`, `Ids`,
`leadId`, `leadIds`, `externalId`. Also rejected: `search`, `status`,
`isDeposited`, `sortBy`, `order`. So the original instinct — that the base
class's `Ids=` call is unusable here — was right, but for a stronger reason than
assumed: the call does not silently return the wrong page, it 400s.

## Response

```json
{"count": 1, "rows": [ ... ]}
```

`count` is the **total matching rows, not the page size**. Confirmed with
`skip=1`: `count=1` with `rows=[]`. So paginate until you have consumed `count`,
do not stop when a page is short.

Observed row, complete and verbatim (lead 27, a QA lead — synthetic data):

```json
{
  "id": "422bd856-1026-4b91-995d-4f0e41019a3b",
  "registration": {"status": "deposited", "rawStatus": "Test Lead"},
  "profile": {"email": "nexora.qatest.t4.20260806@example.com",
              "lastName": "QATest", "firstName": "Nexora"},
  "ip": "187.190.0.3",
  "geo": "MX",
  "utmSource": null, "utmMedium": null, "utmCampaign": null, "utmId": null,
  "subId": "nexora-qa-t4-20260806",
  "subId_a": null, "subId_b": null, "subId_c": null,
  "subId_d": null, "subId_e": null, "subId_f": null,
  "isDeposited": true,
  "createdAt": "2026-08-06T14:49:12.769Z",
  "depositedAt": "2026-08-06T14:59:19.087Z"
}
```

## Mapping to `parse_status_sync_results()`

| Contract key | Source | Note |
|---|---|---|
| `external_id` | `row['id']` | **Not `leadId`.** Injection *responds* with `leadId`; the GET *rows* key the same value as `id`. Anyone implementing from the old docstring would have looked for `leadId` on a row and found nothing. |
| `buyer_status` | `row['registration']['status']` | `"deposited"` observed. `rawStatus` is the broker's own free text (`"Test Lead"`) and is the better candidate for `default_status_mapping`, which is still `{}`. |
| `deposit` | `row['isDeposited']` | Real boolean. |
| `country_iso2` | `row['geo']` | `"MX"` — already alpha-2, matches our convention. |
| `updated_at` | **no clean source** | See below. |

### The `updated_at` gap

There is **no general updated-at field**. A row carries only `createdAt` and
`depositedAt`, and `depositedAt` exists only once a deposit happens. A non-deposit
status change therefore has no timestamp at all. Options, none free:

- use `depositedAt` when present and fall back to sync time otherwise (lossy —
  our record of *when* a status changed becomes "when we noticed");
- ask Hypernet whether an updated-at exists and is simply not returned here.

Not resolved. Do not silently paper over it — `updated_at` feeds
`buyer_status_updated_at`, and a fabricated timestamp is worse than an honest one.

## The window filters on registration date — the approach in the old docstring does not work

This was the open question and it now has a definitive answer. Two complementary
probes against a lead with `createdAt=14:49:12Z` and `depositedAt=14:59:19Z`:

| Window | Result |
|---|---|
| `14:55–15:05` (excludes `createdAt`, includes `depositedAt`) | `count=0` |
| `14:45–14:55` (includes `createdAt`, excludes `depositedAt`) | `count=1` |
| `2020-01-01 – 2020-01-02` (impossible) | `count=0` |

So `from`/`to` filter on **`createdAt`** — registration date — and the params are
genuinely honoured rather than ignored.

**Consequence:** "pull a recent window and match on leadId", the approach the old
`NotImplementedError` proposed, is wrong. A lead that registered last month and
deposits today never appears in a today-window. A sync built that way would look
healthy and silently miss most deposits — the exact failure mode the raise was
there to prevent.

Two approaches that do work:

1. **Window by creation date.** We know each lead's `createdAt` (it is our
   injection time). Pull windows covering the creation dates of leads still in a
   non-terminal state, page with `skip`/`take` (max 500), match on `row['id']`.
   Bulk-efficient; the natural fit for the existing beat task.
2. **Per-lead `email` filter.** Exact and simple, one request per lead. Costlier
   at volume but immune to window arithmetic.

A hybrid is probably right: (1) for the recent bulk, (2) to resolve stragglers.

## Two problems this turned up

### 1. Phantom deliveries — 2 of 3

We hold three `delivered` injections for this buyer with real UUID `external_id`s
returned by their API. **Hypernet has a record of only one.**

| Our lead | `external_id` | Injected | On their side |
|---|---|---|---|
| 24 (t2) | `61e6c7b6-1dfe-4967-aa7e-98af19260924` | 11:45:17Z | **absent** |
| 25 (t3) | `143bb21c-4d8c-4c89-a5b3-5287c95cf0d3` | 11:53:40Z | **absent** |
| 27 (t4) | `422bd856-1026-4b91-995d-4f0e41019a3b` | 14:49:11Z | present |

Confirmed by two independent query paths: an unbounded `2020–2030` window
(`count=1`) and per-email lookups (t2 → `count=0`, t3 → `count=0`, t4 →
`count=1`). Their API returned `success: true` and a UUID for all three.

Unexplained. Something changed between 11:53 and 14:49 — plausibly the box
`affc`/`bxc`/`vtc` constants were corrected in that gap and the earlier two
landed against an invalid target, but that is a hypothesis, not a finding. Needs
Hypernet to confirm whether t2/t3 were rejected post-acknowledgement, purged as
test data, or routed somewhere the GET does not cover.

This matters beyond QA: a `delivered` record we cannot corroborate is a lead we
would bill for and could not defend.

### 2. A deposit we never recorded

Lead 27 **deposited at 14:59:19Z**, ten minutes after injection. Nexora has
`deposit=False`, `buyer_status=''`, `buyer_status_updated_at=None`, and zero
`LeadStatusEvent` rows. Nothing errored, because `supports_status_sync=False`
makes the beat task return before it tries.

It is QA money (`rawStatus: "Test Lead"`), so nothing is owed. But it is a real
conversion event that the pipeline missed end-to-end, which is what the gap costs
once traffic is real.

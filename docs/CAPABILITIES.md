# Nexora Platform — Capability Map

> Documentation only — generated from the code as it exists today. Routes are the
> real `urlpatterns` mounted in `project/urls.py` and the per-app URL confs.
> "Who" = the authorization actually enforced on the view (decorator / permission class).

## Roles & gating primitives

`user_profile.models.Profile` carries the role and (for affiliates) a status:

| Role (`Profile.Role`) | Value |
|---|---|
| Affiliate / Partner | `AFFILIATE` |
| Advertiser | `ADVERTISER` |
| Affiliate Manager | `AFFILIATE_MANAGER` |
| Network Admin | `NETWORK_ADMIN` |

`Profile.AffiliateStatus`: `PENDING` (default) · `APPROVED` · `REJECTED` · `SUSPENDED`,
plus a separate `email_verified` boolean.

Gating helpers:
- **`affiliate_ui.gates.require_approved_affiliate`** — AFFILIATE role **AND** status `APPROVED` **AND** `email_verified`; otherwise 403 (`affiliate_ui/gated.html`).
- **`advertiser.decorators.advertiser_required`** — login + `role == ADVERTISER`, else `PermissionDenied` (403).
- **`affiliate_ui.views.admin_views._require_network_admin`** — `NETWORK_ADMIN` / `AFFILIATE_MANAGER` / `is_superuser`.
- **`staff_member_required`** — Django staff flag (used by payouts, fraud, brands, dashboard).
- **`public_api.views.network.IsNetworkAdmin`** — `is_superuser` or `role == NETWORK_ADMIN`.
- **`api.permissions.IsSuperUser`** — used by the legacy `/api/` viewsets.

Every request gets a `request.brand` from `brands.middleware.BrandMiddleware` (host → Brand, falls back to the default brand).

---

## 1. AFFILIATE / PARTNER — `/partner/` (`affiliate_ui`)

Server-rendered UI. Backward-compat standalone login also at `/login/`.

| Feature | Route | Who | Notes |
|---|---|---|---|
| Home redirect → dashboard | `/partner/` | login | `RedirectView` to `dashboard/` |
| Login | `/partner/login/` | public | `AffiliateLoginView` (redirects authenticated users) |
| Logout | `/partner/logout/` (POST) | login | |
| **Self-registration** | `/partner/register/` | public | Creates `AFFILIATE` profile, status `PENDING`, `email_verified=False`, stamps `request.brand`; sends verification email; auto-login |
| Email verification | `/partner/verify-email/<token>/` | public | Signed token, 24h expiry; flips `email_verified=True` |
| **Dashboard** | `/partner/dashboard/` | login | Clicks/conversions counts + approved earnings. Shows **pending banner** (`is_pending`) for unapproved/unverified affiliates — reachable even when gated |
| Offer list | `/partner/offers/` | **approved affiliate** | Card/grid browse of active offers **within the affiliate's brand**. Combinable server-side filters: search, category, country (applies the offer's include/exclude targeting), revenue model, payout min/max, traffic-source compatibility |
| Offer detail | `/partner/offers/<id>/` | **approved affiliate** | Shows generated tracking link (`TRACKER_URL/click?offer_id=&pid=<user id>`) |
| Report — daily | `/partner/reports/daily/` | login | `affiliate.dao.daily_report`, date range + offer filter |
| Report — by offer | `/partner/reports/offer/` | login | |
| Report — by goal | `/partner/reports/goal/` | login | |
| **Payouts home** | `/partner/payouts/` | **approved affiliate** | Methods, request history, settings, pending (unpaid) earnings |
| Add payout method | `/partner/payouts/methods/add/` (POST) | **approved affiliate** | crypto / mpesa / paypal / paxum / wise / bank; crypto address validated |
| Delete payout method | `/partner/payouts/methods/<pk>/delete/` (POST) | **approved affiliate** | own-record scoped |
| Set default method | `/partner/payouts/methods/<pk>/set-default/` (POST) | **approved affiliate** | |
| **Request early payout** | `/partner/payouts/request/` (POST) | **approved affiliate** | Enforces `min_threshold`; one request per period; advances `paid_through` under a row lock |
| Update payout settings | `/partner/payouts/settings/` (POST) | **approved affiliate** | Payout schedule |
| Address validation (AJAX) | `/partner/payouts/api/validate-address/` | login | Live crypto-address check |
| Fee estimate (AJAX) | `/partner/payouts/api/fee-estimate/` | login | Provider fee estimate |

**Gating states:** a PENDING / unverified affiliate can log in and view the dashboard
(with a pending banner) but is **blocked** (403) from offers, offer detail / tracking links,
and all payout pages. REJECTED / SUSPENDED behave the same (only `APPROVED` passes the gate).

**Smart links:** there is **no affiliate-facing smart-link CRUD** in the code today — smart links
are created/managed in the Django model admin (see §3). The public redirect endpoint is `/sl/<alias>`
(see Tracking & redirects). The gate docstring references smart-link management as a future blocked surface.

**Affiliate REST API** (`/affiliate/…`) is a separate JSON surface, also usable by an affiliate (see §5).

---

## 2. ADVERTISER — `/advertiser/` (`advertiser_ui`)

Server-rendered UI, all guarded by `advertiser_required`. Views degrade to a
"no account" page if the user has no `advertiser_profile`.

| Feature | Route | Who | Notes |
|---|---|---|---|
| **Dashboard** | `/advertiser/` | advertiser | Today / 7d / 30d stats |
| Offers (list) | `/advertiser/offers/` | advertiser | List with status filter + counts |
| **Offer create** | `/advertiser/offers/new/` | advertiser | Self-service create — auto-stamped with the advertiser + `request.brand`. Fields: name, category, description, creative image/URL (with preview), revenue model + initial payout + currency, accepted traffic sources, country targeting (mode + list), tracking/preview URL, status |
| Offer edit | `/advertiser/offers/<id>/edit/` | advertiser | Own offer only (scoped to advertiser + brand) |
| Offer pause/activate | `/advertiser/offers/<id>/status/` (POST) | advertiser | Own offer only |
| **Conversions** | `/advertiser/conversions/` | advertiser | Paginated, filter by offer/status/date/sub1–5 |
| Conversions bulk action | `/advertiser/conversions/bulk/` (POST) | advertiser | approve / reject / hold (own offers only) |
| Conversions CSV export | `/advertiser/conversions/export/` | advertiser | |
| **Postbacks** | `/advertiser/postbacks/` | advertiser | Shows canonical + HMAC-signed postback URL, inbound log, HMAC enforce flag |
| Regenerate postback secret | `/advertiser/postbacks/regenerate/` (POST) | advertiser | Rotates HMAC key |
| **MMP callbacks** | `/advertiser/mmp/` | advertiser | Last-24h MMP callback log + per-offer MMP config (read-only view) |
| **Wallet** | `/advertiser/wallet/` | advertiser | Balance, transactions, top-ups, invoices (`billing` app) |
| Settings | `/advertiser/settings/` | advertiser | Edit country |
| Logout | `/advertiser/logout/` | any | Redirects to affiliate login |

**Billing / wallet model** (`billing`): `AdvertiserWallet` → `WalletTopUp`, `WalletTransaction`,
`Invoice`. Top-up webhooks: `/webhooks/stripe/` and `/webhooks/paystack/` (public, signature-verified;
`billing.urls`). Wallet balance also exposed read-only via the Public API.

**Advertiser REST API** (`/api/v1/advertiser/…`) gives true offer CRUD + conversion bulk actions + wallet (§5).

---

## 3. NETWORK ADMIN / OPERATOR — `/admin/…`

Two layers: the custom operator tools (templated pages) and the Django **model admin**.

### 3a. Operator tools

| Tool | Route | Who | Notes |
|---|---|---|---|
| **Operator dashboard** | `/admin/dashboard/` | `staff_member_required` | Nav cards + at-a-glance stats. Affiliate stats brand-scoped (`request.brand`); payout & fraud counts network-wide |
| **Affiliate mgmt — list** | `/admin/affiliates/` | network-admin / affiliate-manager / superuser | Brand-scoped affiliate list, status filter |
| Affiliate approve | `/admin/affiliates/<pk>/approve/` (POST) | same | Sets `APPROVED`, emails the affiliate |
| Affiliate reject | `/admin/affiliates/<pk>/reject/` (POST) | same | Sets `REJECTED` |
| Affiliate suspend | `/admin/affiliates/<pk>/suspend/` (POST) | same | Sets `SUSPENDED` |
| **Payouts — list** | `/admin/payouts/` | `staff_member_required` | Payout requests |
| Payouts bulk approve | `/admin/payouts/approve/` (POST) | staff | |
| Payouts mark paid | `/admin/payouts/mark-paid/` (POST) | staff | |
| Payouts dispatch approved | `/admin/payouts/dispatch/` (POST) | staff | Triggers provider dispatch |
| Payouts batch CSV | `/admin/payouts/csv/` | staff | |
| Payout batches | `/admin/payouts/batches/` | staff | |
| **Fraud dashboard** | `/admin/fraud/` | `staff_member_required` | Flagged clicks/conversions (24h), top IPs, reason tallies |
| Fraud whitelist add | `/admin/fraud/whitelist/add/` (POST) | staff | |
| Fraud whitelist remove | `/admin/fraud/whitelist/remove/<pk>/` (POST) | staff | |
| **Brands — list** | `/admin/brands/` | `staff_member_required` | |
| Brand create | `/admin/brands/new/` | staff | |
| Brand edit | `/admin/brands/<pk>/edit/` | staff | |
| Brand delete | `/admin/brands/<pk>/delete/` | staff | |
| Brand setup instructions | `/admin/brands/<pk>/setup/` | staff | Post-create DNS/domain setup help page |

Payout provider webhooks (public, signature-verified, `payouts.webhook_urls`):
`/webhooks/mpesa/b2c/`, `/webhooks/nowpayments/`.

### 3b. Django model admin — `/admin/` (`staff_member_required`)

Registered models available in the stock Django admin:

| App | Models registered |
|---|---|
| `offer` | Offer, Category, TrafficSource, Goal, Payout, Currency, Advertiser |
| `tracker` | Click, Conversion |
| `smartlinks` | **SmartLink, SmartLinkClick** (smart-link + routing-rule management lives here) |
| `postback` | Postback, Log |
| `mmp` | MMP, MMPCallback |
| `billing` | AdvertiserWallet, WalletTopUp, WalletTransaction, Invoice |
| `fraud` | FraudWhitelist |
| `user_profile` | Profile |

The Django admin header is overridden (`templates/admin/base_site.html`) to add a
"→ Operator Dashboard" button.

### 3c. Reporting

- Materialized-view backend abstraction (`reporting.backends`), Postgres default, ClickHouse stub.
- 4 matviews (`reporting_click_hourly/daily`, `reporting_conversion_hourly/daily`) refreshed every 5 min by Celery beat.
- Surfaced through the read API (`/api/v1/reports/*`, §5) and the operator dashboard stats.

### 3d. Network REST API (legacy) — `/network/…`

DRF, `IsAuthenticated + IsAdminUser` (Django staff). Read-only across all affiliates/offers.

| Endpoint | Route |
|---|---|
| Affiliates list / detail | `/network/affiliates/`, `/network/affiliates/<pk>/` |
| Offers list / detail | `/network/offers/`, `/network/offers/<pk>/` |
| Stats — daily / offers / affiliates | `/network/stats/daily/`, `/stats/offers/`, `/stats/affiliates/` |
| Conversions | `/network/conversions/` |

---

## 4. BRAND (white-label layer) — `brands`

A `Brand` is the white-label tenant. Model fields:
`slug`, `name`, `primary_domain` (unique), `tracking_domain` (unique), `logo`, `favicon`,
`primary_color`, `secondary_color`, `support_email`, `terms_url`, `privacy_url`, `is_default`.

**What a Brand controls (theming/identity):** name, logos/favicon, brand colors, support email,
terms & privacy URLs. These flow into every template via `brands.context_processors.brand_context`
(the `brand` template variable) and into transactional emails (verification & approval emails use the
brand name and primary domain).

**Custom domains / routing:**
- `BrandMiddleware` resolves each request: `HTTP_HOST` (lowercased, port-stripped) is matched against
  `primary_domain` **or** `tracking_domain`; if no match, `Brand.get_default()` is used. Result is set as `request.brand`.
- So a brand is reached purely by pointing its custom domain (app + tracking) at the platform — no per-brand deploy.
- `is_default` is enforced singleton-style: saving a brand with `is_default=True` clears the flag on all others.
- The operator "brand setup" page (`/admin/brands/<pk>/setup/`) shows the DNS/domain wiring instructions.

**What is isolated per brand (brand-scoped data):**
- `offer.Offer.brand`, `offer.Advertiser.brand`, `tracker.Conversion.brand` (via `BrandScopedManager`).
- `user_profile.Profile.brand` — affiliates are stamped with the brand they registered under; the
  affiliate-management list and approve/reject/suspend actions are filtered to `request.brand`.
- `public_api.WebhookEndpoint.brand` — webhook subscriptions are per brand.
- The Public API advertiser/admin endpoints and the reporting API all scope queries to `request.brand`.

**What is NOT brand-scoped (network-wide):** payouts (`PayoutRequest`, payout admin), fraud
review/whitelist, and the operator payout/fraud counts on the dashboard. The dashboard comments call
this out explicitly.

---

## 5. PUBLIC API SURFACE

### 5a. `/api/v1/…` (`public_api` + `reporting`) — the documented v1 API

**Auth:** `Authorization: ApiKey <secret>` (`APIKeyAuthentication`) **or** exchange client
credentials for a 1-hour JWT at `POST /api/v1/auth/token`. JWT, Basic, and Session auth are also
accepted (DRF defaults). **Throttle:** per-API-key, `APIKey.requests_per_hour` (default 1000/hour, Redis-backed).
All resource queries are scoped to `request.brand`.

| Endpoint | Method | Who can use it |
|---|---|---|
| `/api/v1/auth/token` | POST | **public** (client_id + client_secret → JWT) |
| `/api/v1/auth/keys` | GET / POST | any authenticated user (lists/creates **own** keys) |
| `/api/v1/auth/keys/<pk>` | DELETE | owner (deactivates own key) |
| `/api/v1/advertiser/offers` | GET / POST | **Advertiser** (has `advertiser_profile`); scoped to own offers + brand |
| `/api/v1/advertiser/offers/<pk>` | GET / PATCH / DELETE | Advertiser (own offer) |
| `/api/v1/advertiser/conversions` | GET | Advertiser (own offers' conversions) |
| `/api/v1/advertiser/conversions/bulk_approve` | POST | Advertiser |
| `/api/v1/advertiser/conversions/bulk_reject` | POST | Advertiser |
| `/api/v1/advertiser/wallet` | GET | Advertiser (own balance) |
| `/api/v1/admin/offers` | GET / POST | **Network Admin / superuser** (all brand offers) |
| `/api/v1/admin/offers/<pk>` | GET / PATCH / DELETE | Network Admin / superuser |
| `/api/v1/admin/advertisers` | GET | Network Admin / superuser |
| `/api/v1/admin/conversions` | GET | Network Admin / superuser |
| `/api/v1/admin/webhooks` | GET / POST | Network Admin / superuser (brand-scoped) |
| `/api/v1/admin/webhooks/<pk>` | GET / DELETE | Network Admin / superuser |
| `/api/v1/admin/webhooks/<pk>/deliveries` | GET | Network Admin / superuser (delivery log) |
| `/api/v1/reports/clicks` | GET | any authenticated user; results scoped to `request.brand` |
| `/api/v1/reports/conversions` | GET | any authenticated user; brand-scoped |
| `/api/v1/reports/revenue` | GET | any authenticated user; brand-scoped (EPC/CR) |

Reports support `date_from`/`date_to`, `group_by` (period, offer, affiliate, country,
traffic_source, device, brand), filters, cursor pagination, and ETag/304 caching.

**Webhook delivery (outbound):** HMAC-SHA256 (`X-Nexora-Signature: sha256=<hex>`), events
`offer.created`, `conversion.approved`, `payout.paid`; retries 60s→300s→1800s then `failed`.

### 5b. `/api/…` (legacy `api` app) — superuser-only DRF

`IsAuthenticated + IsSuperUser` on every endpoint.

| Endpoint | Route |
|---|---|
| Offers (CRUD) | `/api/offers/` (router viewset) |
| Advertisers (CRUD) | `/api/advertisers/` |
| Landings (CRUD) | `/api/landings/` |
| Payouts (CRUD) | `/api/payouts/` |
| Traffic sources (CRUD) | `/api/traffic-sources/` |
| Create conversion | `/api/conversions/` (POST) |

### 5c. `/affiliate/…` (legacy `affiliate` app) — affiliate self-service API

DRF. Sign-up is `AllowAny`; everything else `IsAuthenticated` (acts on the calling affiliate).

| Endpoint | Route | Who |
|---|---|---|
| Sign-up | `/affiliate/sign-up/` | public |
| Profile | `/affiliate/profile/` | authenticated affiliate |
| Offers list / detail | `/affiliate/offers/`, `/affiliate/offers/<pk>/` | authenticated |
| Tracking link | `/affiliate/offers/<pk>/tracking-link/` | authenticated |
| Stats — daily / offers / by-goal / by-sub | `/affiliate/stats/daily/`, `/stats/offers/`, `/stats/by-goal/`, `/stats/by-sub/<sub>/` | authenticated |
| Conversions | `/affiliate/conversions/` | authenticated |

### 5d. `/network/…` — see §3d (admin/staff, read-only).

### 5e. Dictionaries — `/api/countries/`, `/api/categories/` (`dictionaries`)

Reference lists (countries from `countries_plus`, offer categories).

### 5f. Schema / docs

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/schema/swagger-ui/` (and legacy alias `/api/`)
- JWT (generic): `/api/token/`, `/api/token/refresh/`
- Postman collection: `docs/postman_collection.json`

---

## Tracking, redirects & integration endpoints (public)

These are unauthenticated by design (they serve clicks/postbacks/callbacks on the tracking domain):

| Endpoint | Route | App | Purpose |
|---|---|---|---|
| Click | `/click` | `tracker` | Click tracking & redirect |
| Postback | `/postback` | `tracker` | Conversion postback (HMAC optional, `ENFORCE_POSTBACK_HMAC`) |
| Smart link | `/sl/<alias>` | `smartlinks` | Geo/device-routed redirect; logs click if `pid` present |
| MMP callback | `/mmp/callback/<vendor>/` | `mmp` | Mobile-measurement-partner callbacks |
| Stripe top-up webhook | `/webhooks/stripe/` | `billing` | Wallet top-up |
| Paystack top-up webhook | `/webhooks/paystack/` | `billing` | Wallet top-up |
| M-Pesa B2C webhook | `/webhooks/mpesa/b2c/` | `payouts` | Payout dispatch callback |
| NOWPayments IPN | `/webhooks/nowpayments/` | `payouts` | Crypto payout callback |
| Health check | `/healthz` | `project` | Liveness |
| Public landing | `/` | `website` | Brand-aware marketing landing |

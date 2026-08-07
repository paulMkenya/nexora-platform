# Nexora Platform

CPA affiliate network platform — Django 5.2, Celery, Gunicorn, PostgreSQL 16, Redis 7.

## Key Configuration

| Variable | Value |
|----------|-------|
| `PRIMARY_DOMAIN` | `cpa.cloudtrade.pro` |
| `TRACKING_DOMAIN` | `t.cloudtrade.pro` |
| `ADMIN_EMAIL` | `support@cloudtrade.pro` |
| `APP_DIR` | `/opt/nexora-platform` |
| `DEPLOY_USER` | `deploy` |
| Git remote | `git@github.com:paulMkenya/nexora-platform.git` |

## Production Deployment

### Compose file
```
/opt/nexora-platform/docker-compose.prod.yml
```

Always run compose commands from `APP_DIR` or with the full `-f` path:
```bash
docker compose -f /opt/nexora-platform/docker-compose.prod.yml <command>
```

### Containers

| Container | Role | Networks |
|-----------|------|----------|
| `nexora-web` | Gunicorn WSGI (port 8000) | `cloudtrade-internal`, `cloudtrade-proxy` |
| `nexora-worker` | Celery async worker | `cloudtrade-internal` |
| `nexora-beat` | Celery beat scheduler (offer cache every 60s) | `cloudtrade-internal` |

### Environment file
```
/opt/nexora-platform/.env.prod   (chmod 600, owned by deploy)
```
Required vars: `DJ_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `TRACKER_URL`, `IPSTACK_TOKEN` (optional), `SENTRY_DSN` (optional).

**Never quote a value in this file** — not `'single'`, not `"double"`. Docker
Compose strips surrounding quotes; `docker run --env-file` passes them through
literally. A quoted value therefore means one-off containers get a *different*
value than the running stack, and for `DJ_SECRET_KEY` that is silently
destructive: `nexora.crypto` derives its Fernet key from `SECRET_KEY`, and
`decrypt_secret` swallows `InvalidToken` and returns `''` rather than raising.
The symptom is a management command run exactly as documented below getting a
zero-length API key and the buyer answering `401`, with nothing in any log
saying why. `DJ_SECRET_KEY` was quoted until 2026-08-07. The file now carries a
`# DO NOT QUOTE` comment above it.

### Secrets
```
/root/nexora-platform-secrets.txt   (chmod 600, owned by root)
```
Contains Django admin credentials.

## Shared Infrastructure — DO NOT RECREATE

These containers are shared across the cloudtrade stack. Never add postgres or redis services to any compose file.

| Container | Image | Network | Credentials |
|-----------|-------|---------|-------------|
| `cloudtrade-postgres` | postgres:16 | `cloudtrade-internal` | user: `cloudtrade`, db: `cloudtrade_main` |
| `cloudtrade-redis` | redis:7-alpine | `cloudtrade-internal` | password in `.env.prod` |
| `nginx-proxy-manager` | jc21/nginx-proxy-manager | `cloudtrade-proxy` | Admin: `http://127.0.0.1:81` |

`nexora-web` must always be on **both** `cloudtrade-internal` (reaches DB/Redis) and `cloudtrade-proxy` (reachable by NPM). Worker and beat only need `cloudtrade-internal`.

## Django Apps & URL Routes

| URL prefix | App | Purpose |
|------------|-----|---------|
| `/admin/` | Django admin | Staff admin panel (model admin) |
| `/admin/dashboard/` | `brands.views.admin_views.dashboard` | Operator home — nav cards + at-a-glance stats |
| `/admin/affiliates/` | `affiliate_ui` | Affiliate management (approve/reject/suspend) |
| `/admin/leads/` | `leads` | Brand-scoped CRM lead pipeline (affiliates + advertisers) |
| `/admin/payouts/` | `payouts` | Payout requests (approve, dispatch, CSV, batches) |
| `/admin/fraud/` | `fraud` | Fraud review (flagged clicks/conversions, whitelist) |
| `/admin/brands/` | `brands` | Brand CRUD + setup |
| `/login/`, `/dashboard/` | `affiliate_ui` | Server-rendered affiliate UI |
| `/api/` | `api` + `dictionaries` | REST API + Swagger at `/api/` |
| `/affiliate/` | `affiliate` | Affiliate API |
| `/network/` | `network` | Network management API |
| `/click` | `tracker` | Click tracking (TRACKING_DOMAIN) |
| `/postback` | `tracker` | Conversion postback (TRACKING_DOMAIN) |

## Common Operations

### Rebuild and redeploy
```bash
cd /opt/nexora-platform
docker build -f docker/Dockerfile.prod -t nexora-platform:latest .
docker compose -f docker-compose.prod.yml up -d
```

### Run migrations
```bash
docker run --rm --network cloudtrade-internal --env-file /opt/nexora-platform/.env.prod \
  nexora-platform:latest python manage.py migrate
```

### Open Django shell
```bash
docker exec -it nexora-web python manage.py shell
```

### View logs
```bash
docker compose -f /opt/nexora-platform/docker-compose.prod.yml logs -f nexora-web
docker compose -f /opt/nexora-platform/docker-compose.prod.yml logs -f nexora-worker
```

### Database access
```bash
docker exec -it cloudtrade-postgres psql -U cloudtrade -d cloudtrade_main
```

## Settings

Settings module: `project.settings` → tries `local.py`, falls back to `prod.py` (production).
Static files: served by Whitenoise from `/app/staticfiles/` (collected on each `nexora-web` startup).

A project-level template dir is enabled (`TEMPLATES['DIRS'] = [BASE_DIR/templates]`), searched
before app templates — used for the admin overrides and shared admin partials below.

## Operator Admin UI

The custom (non-model) operator tools live under `/admin/*` (see the URL table above) and are
gated by `staff_member_required`, except `/admin/affiliates/` which uses a network-admin /
affiliate-manager / superuser role check. `/admin/dashboard/` is the operator home.

- **Shared nav:** `templates/admin_shared/nav.html` — a self-contained, framework-agnostic header
  (works on both the Bootstrap and Tailwind admin pages) included across affiliates, payouts,
  fraud, brands and the dashboard. Pass `active` to highlight the current tool.
- **Dashboard:** `templates/admin_shared/dashboard.html`, rendered by `brands.views.admin_views.dashboard`.
  Brand-scoped affiliate stats (via `request.brand`); payout/fraud counts are network-wide.
- **Django admin link:** `templates/admin/base_site.html` overrides the admin header to add a
  prominent "→ Operator Dashboard" button. Do not remove the override or the link disappears.
- **Brand form prefill (gotcha):** `brands/admin/brand_form.html` prefills every input from a
  single `post` mapping built by `brands.views.admin_views._form_data(request, brand=None)` — a
  `defaultdict(str)` seeded from the edited brand on GET and overridden by `request.POST` on a
  validation re-render. Two traps this guards against, both of which previously 500'd / leaked data:
  1. A missing template variable used as a **filter argument** (e.g. the old
     `{{ brand.x|default:post.x }}` when `post` was absent) raises `VariableDoesNotExist` — it is
     **not** swallowed like a missing top-level variable. So `post` must resolve for every field on
     every render path (GET and POST-error alike); the `defaultdict(str)` guarantees that.
  2. Do **not** prefill the brand form from the `brand` template variable — that is the *request's*
     brand injected by `brands.context_processors` and would leak the current brand onto the create
     form. Prefill only from `post`.

## Currencies & Country (data conventions)

- **Currencies:** `offer.Currency` (`code`, `name`, `symbol`) is the single currency source,
  seeded with all ISO-4217 currencies (~155) by `offer/migrations/0028_seed_currencies.py` from
  `offer/currencies.py`. The seed is idempotent (matched by `code`) — re-running keeps existing
  rows and their FKs (`offer.Payout.currency`). Use `offer.currencies.currency_choices()` for any
  new currency dropdown. Free-text currency CharFields (`payouts`, `billing`) keep their stored
  values; the billing wallet admin renders currency as a dropdown.
- **Country:** the single source of country data is **`countries_plus`** (252 rows) — never add
  another. Country is stored as the **ISO-3166-1 alpha-2 code** on `user_profile.Profile.country`
  and `offer.Advertiser.country` (blank = unset). Build dropdowns with
  `user_profile.geo.country_choices()` (name + ISO, alpha-2 sort); display stored codes with the
  `geo_extras` template tags (`country_flag`, `country_name`, `country_display`).
  `offer/migrations/0029_standardize_country.py` is the backfill safety net (maps names→codes,
  logs unmatched, never deletes).

## Reporting Architecture (Sprint 8)

### Backend abstraction
The reporting layer uses a pluggable `AggregationBackend` interface (`reporting/backends/base.py`).
The active backend is selected by `REPORTING_BACKEND` in Django settings.

| Value | Implementation | Status |
|-------|---------------|--------|
| `'postgres'` | `PostgresMatViewBackend` (default) | Active |
| `'clickhouse'` | `ClickHouseBackend` | Future |

### Postgres materialized views
Four matviews are created by `reporting/migrations/0001_reporting_matviews.py`:
- `reporting_click_hourly` / `reporting_click_daily`
- `reporting_conversion_hourly` / `reporting_conversion_daily`

Refreshed every **5 minutes** by the `refresh-reporting-views` Celery beat task.

### ClickHouse upgrade trigger
When any brand exceeds **~10M clicks/month**, switch to ClickHouse:
1. `pip install clickhouse-driver` (or `clickhouse-connect`)
2. Implement `ClickHouseBackend(AggregationBackend)` in `reporting/backends/clickhouse.py`
3. Set `REPORTING_BACKEND=clickhouse` in `.env.prod`

No view, URL, serializer, or test code needs to change — only the backend implementation.

### Public API (Sprint 8)
- API key auth: `Authorization: ApiKey <secret>` — or exchange for JWT via `POST /api/v1/auth/token`
- Swagger UI: `/api/schema/swagger-ui/`
- Postman collection: `docs/postman_collection.json`

Rate limiting is per-API-key (`APIKey.requests_per_hour`, default 1000). Backed by Redis.

Webhook delivery uses HMAC-SHA256 (`X-Nexora-Signature: sha256=<hex>`).
Retry schedule: 60s → 300s → 1800s (3 attempts).  After 3 failures the delivery is marked `failed`.

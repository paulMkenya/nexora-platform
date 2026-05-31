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
| `/admin/` | Django admin | Staff admin panel |
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

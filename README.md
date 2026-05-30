# Nexora

CPA affiliate network platform — Django 5.2, Celery, Gunicorn, PostgreSQL 16, Redis 7.

## Table of Contents

*   [About](#about)
*   [Features](#features)
    *   [Affiliate UI](#affiliate-ui)
    *   [Advertiser Portal](#advertiser-portal)
    *   [REST API](#rest-api)
*   [Getting Started](#getting-started)
    *   [Prerequisites](#prerequisites)
    *   [Installation](#installation)
    *   [Environment Variables](#environment-variables)
*   [License](#license)

## About

Nexora is a robust and scalable affiliate marketing platform designed for managing CPA campaigns. It provides the core infrastructure for tracking, reporting, and optimizing performance for Cost Per Action (CPA) campaigns, with server-rendered UIs for both affiliates and advertisers.

**Keywords:** Affiliate Tracking Software, CPA Platform, Affiliate Management Platform, Performance Marketing Backend and UI


## Features

### Affiliate UI

Server-rendered Affiliate User Interface at `/login/` and `/dashboard/`.

*   **Login & Authentication:** Secure web-based login; role-based portal routing on sign-in.
*   **Dashboard:** Summary of clicks, conversions, and earnings.
*   **Offer Browsing:** Browse, search, and filter available offers.
*   **Detailed Reports:** Daily, offer-level, and goal-level reports.


### Advertiser Portal

Server-rendered Advertiser Portal at **`https://cpa.cloudtrade.pro/advertiser/`** (Tailwind CSS + HTMX).

*   **Dashboard:** Stats for today / last 7 days / last 30 days — clicks, conversions, CR%, approved payout. Top 5 offers by revenue. 60-second Redis cache per advertiser.
*   **Offers:** Full offer list with 30-day stats (clicks, conversions, approved revenue, best payout) annotated via correlated Postgres subqueries. Status filter pills.
*   **Conversions:** Paginated list with filters (offer, status, date range, sub IDs). Bulk Approve / Hold / Reject with reason; fires outbound postbacks via Celery. CSV export of current filter.
*   **Postbacks:** Inbound S2S postback URL manager. Per-advertiser HMAC-SHA256 secret with copy/reveal/regenerate UI. Shows last 50 inbound postback attempts with HMAC verification status. HMAC enforcement gated behind `ENFORCE_POSTBACK_HMAC` feature flag (default off).


### REST API

*   **Affiliate API** (`/affiliate/`): Offers, tracking links, conversions, stats.
*   **Network API** (`/network/`): Affiliates, offers, conversions, stats (staff only).
*   **Admin CRUD API** (`/api/`): Offers, advertisers, payouts, landings, traffic sources; gated by `IsSuperUser`.
*   **Swagger UI** at `/api/`.


## Getting Started

Follow these steps to get a local copy of the project up and running.

### Prerequisites

*   [Docker](https://www.docker.com/get-started)
*   [Docker Compose](https://docs.docker.com/compose/install/)

### Installation

1.  **Clone the repository:**

    ```bash
    git clone git@github.com:paulMkenya/nexora-platform.git
    ```

2.  **Configure Environment Variables:**

    ```bash
    cp project/settings/local.dist.py project/settings/local.py
    cp .env.dist .env
    # Edit .env — see Environment Variables section below
    ```

3.  **Database schema and data:**

    ```bash
    docker compose run --rm web python manage.py migrate
    docker compose run --rm web python manage.py update_countries_plus
    docker compose run --rm web python manage.py createsuperuser
    ```

4.  **Start the Development Environment:**

    ```bash
    docker compose up
    ```

5.  **Open the UIs:**

    | Portal | URL |
    |--------|-----|
    | Django Admin | http://127.0.0.1:8000/admin/ |
    | Affiliate UI | http://127.0.0.1:8000/login/ |
    | Advertiser Portal | http://127.0.0.1:8000/advertiser/ |
    | API (Swagger) | http://127.0.0.1:8000/api/ |


### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DJ_SECRET_KEY` | ✓ | Django secret key |
| `DATABASE_URL` | ✓ | Postgres connection string, e.g. `postgres://user:pass@host/db` |
| `REDIS_URL` | ✓ | Redis connection string, e.g. `redis://:pass@host:6379/0`. Used for Celery broker and Django cache. |
| `TRACKER_URL` | ✓ | Base URL of the tracking domain, e.g. `https://t.cloudtrade.pro` |
| `DJANGO_ALLOWED_HOSTS` | ✓ (prod) | Comma-separated allowed hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | ✓ (prod) | Comma-separated CSRF trusted origins |
| `IPSTACK_TOKEN` | | IP geolocation token (optional) |
| `SENTRY_DSN` | | Sentry error tracking DSN (optional) |
| `ENFORCE_POSTBACK_HMAC` | | Set to `true` to reject inbound postbacks with invalid/missing HMAC signatures. Default: `false` (logs but accepts). |


## License

Distributed under the MIT License. See `LICENSE` for more information.

# Nexora

CPA affiliate network platform — Django 5.2, Celery, Gunicorn, PostgreSQL 16, Redis 7.

## Table of Contents

*   [About](#about)
*   [Features](#features)
    *   [Affiliate UI](#affiliate-ui)
    *   [REST API](#rest-api)
*   [Getting Started](#getting-started)
    *   [Prerequisites](#prerequisites)
    *   [Installation](#installation)
*   [License](#license)

## About

Nexora is a robust and scalable affiliate marketing platform designed for managing CPA campaigns. It provides the core infrastructure for tracking, reporting, and optimizing performance for Cost Per Action (CPA) campaigns, with a server-rendered affiliate user interface.

**Keywords:** Affiliate Tracking Software, CPA Platform, Affiliate Management Platform, Performance Marketing Backend and UI


## Features

### Affiliate UI

Server-rendered Affiliate User Interface providing an out-of-the-box experience for affiliates to manage their campaigns and view their performance.

Key functionalities include:

*   **Affiliate Login & Authentication:** Secure web-based login for affiliates.
*   **Main Dashboard View:** A summary of performance metrics (clicks, conversions, earnings) upon login.
*   **Offer Browsing:** Ability to browse, search, and filter available offers.
*   **Detailed Reports**


### REST API
*   **Affiliate Registration:** Allows new affiliates to sign up and manage their accounts.
*   **Offer Management:** Comprehensive tools for creating, configuring, and managing advertising offers.
*   **Conversion Import:** Facilitates the import of conversion data from various sources for accurate tracking.
*   **Reports:** Generates detailed reports on campaign performance, conversions, and affiliate earnings.


## Getting Started

Follow these steps to get a local copy of the project up and running for development and testing purposes.

### Prerequisites

Ensure you have the following installed on your system:

*   [Docker](https://www.docker.com/get-started)
*   [Docker Compose](https://docs.docker.com/compose/install/)

### Installation

1.  **Clone the repository:**

    ```bash
    git clone git@github.com:paulMkenya/nexora-platform.git
    ```

2.  **Configure Environment Variables:**
    *   Copy the example local settings file:
        ```bash
        cp project/settings/local.dist.py project/settings/local.py
        ```
    *   Copy the example environment variables file:
        ```bash
        cp .env.dist .env
        ```

3. **Database schema and data**
    * Migrations
        ```bash
        docker-compose run --rm web ./docker/wait-for-postgres.sh "poetry run python manage.py migrate"
        ```

    * Load the countries into database
        ```bash
        docker compose run --rm web poetry run python manage.py update_countries_plus
        ```

    * Create admin user
      ```bash
      docker compose run --rm web poetry run python manage.py createsuperuser
      ```

4.  **Start the Development Environment:**

    ```bash
    docker compose up
    ```

5. **Open Admin UI and Affiliate UI**
    *   **Django Admin:** [http://127.0.0.1:8000/admin/login/](http://127.0.0.1:8000/admin/login/)
    *   **Affiliate UI:** [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/)


## License

Distributed under the MIT License. See `LICENSE` for more information.

import os
import datetime
import dj_database_url


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if o.strip()
]

# Trust X-Forwarded-Proto set by Nginx Proxy Manager (TLS termination)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',
    'countries_plus',
    'tinymce',
    'drf_spectacular',

    'brands',
    'offer',
    'affiliate',
    'network',
    'tracker',
    'user_profile',
    'api',
    'postback',
    'affiliate_ui',
    'advertiser',
    'advertiser_ui',
    'smartlinks',
    'fraud',
    'mmp',
    'billing',
    'payouts',
    'reporting',
    'public_api',
    'website',
    'impersonation',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Swaps request.user to the impersonated target (re-validated every request)
    # BEFORE brand/role routing runs, so the request is handled as the target.
    'impersonation.middleware.ImpersonationMiddleware',
    'brands.middleware.BrandMiddleware',
    'user_profile.middleware.RolePortalMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'brands.context_processors.brand_context',
                'brands.context_processors.operator_roles',
            ],
        },
    },
]

WSGI_APPLICATION = 'project.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#     }
# }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': (
            'django.contrib.auth.password_validation'
            '.UserAttributeSimilarityValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.MinimumLengthValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation'
            '.CommonPasswordValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.NumericPasswordValidator'
        ),
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_URL = '/static/'

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_STORAGE = (
    'whitenoise.storage.CompressedManifestStaticFilesStorage'
)

LOGIN_REDIRECT_URL = '/partner/dashboard/'
LOGIN_URL = '/partner/login/'

# Hosts on which the Django *model admin* (django.contrib.admin) is allowed.
# On any other (brand/tenant) host the model admin and its login are never
# served — requests are redirected to the brand's operator login — so Django
# branding never leaks onto a white-labelled domain. Defaults to the platform
# owner's primary domain; override via env (comma-separated).
PLATFORM_ADMIN_HOSTS = [
    h.strip().lower()
    for h in os.environ.get('PLATFORM_ADMIN_HOSTS', 'cpa.cloudtrade.pro').split(',')
    if h.strip()
]

# Branding for the Django model admin chrome (see project/urls.py).
ADMIN_SITE_HEADER = os.environ.get('ADMIN_SITE_HEADER', 'Nexora Platform Admin')

# Email — driven by env. When EMAIL_HOST is set (in .env.prod) real SMTP is used;
# otherwise we fall back to the console backend so the app never errors on a
# missing mail server (the messages are logged instead of sent). The test runner
# overrides this with the locmem backend automatically.
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST
    else 'django.core.mail.backends.console.EmailBackend',
)
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
# Short SMTP connection timeout so an unreachable mail host can't hang a request.
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@cloudtrade.pro')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
PASSWORD_RESET_TIMEOUT = int(os.environ.get('PASSWORD_RESET_TIMEOUT', str(60 * 60 * 24)))  # 24h

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'public_api.authentication.APIKeyAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'api_key': '1000/hour',
    },
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework.parsers.JSONParser',
        # 'rest_framework.parsers.MultiPartParser',
        # 'rest_framework.parsers.FormParser',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}


SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': datetime.timedelta(days=1),
}


AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]


CORS_ORIGIN_ALLOW_ALL = True

CORS_ALLOW_METHODS = (
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
)

DATABASE_URL = os.environ['DATABASE_URL']

DATABASES = {
    'default': dj_database_url.config(
        default=DATABASE_URL,
        engine='django.db.backends.postgresql_psycopg2')
}

REDIS_URL = os.environ['REDIS_URL']

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
    }
}

TRACKER_URL = os.environ['TRACKER_URL']

# Set to True in env to start rejecting postbacks with invalid/missing HMAC.
# Default False so existing integrations are not broken during rollout.
ENFORCE_POSTBACK_HMAC = os.environ.get('ENFORCE_POSTBACK_HMAC', 'false').lower() == 'true'

IPSTACK_TOKEN = os.environ.get('IPSTACK_TOKEN', '')
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')

# GeoLite2 database paths (mounted from host or bundled in image)
# Fraud engine config
FRAUD_AUTO_REJECT_AT = int(os.environ.get('FRAUD_AUTO_REJECT_AT', '70'))
IPQS_API_KEY = os.environ.get('IPQS_API_KEY', '')  # blank = feature disabled

# Payment provider keys (blank = feature disabled)
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')

# Media files (invoice PDFs etc.)
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(BASE_DIR, 'media'))
MEDIA_URL = '/media/'

# Payout provider keys (blank = feature disabled)
WISE_API_KEY = os.environ.get('WISE_API_KEY', '')
WISE_PROFILE_ID = os.environ.get('WISE_PROFILE_ID', '')
MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', '')
MPESA_B2C_SHORTCODE = os.environ.get('MPESA_B2C_SHORTCODE', '')
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', '')
PAYPAL_CLIENT_SECRET = os.environ.get('PAYPAL_CLIENT_SECRET', '')
PAXUM_ACCOUNT_EMAIL = os.environ.get('PAXUM_ACCOUNT_EMAIL', '')
NOWPAYMENTS_API_KEY = os.environ.get('NOWPAYMENTS_API_KEY', '')
NOWPAYMENTS_IPN_SECRET = os.environ.get('NOWPAYMENTS_IPN_SECRET', '')
CRYPTO_HOT_WALLET_KEY = os.environ.get('CRYPTO_HOT_WALLET_KEY', '')
# 'nowpayments' (default) or 'self_custodial'
CRYPTO_PAYOUT_PROVIDER = os.environ.get('CRYPTO_PAYOUT_PROVIDER', 'nowpayments')

# Reporting aggregation backend.  'postgres' = materialized views (default).
# Switch to 'clickhouse' when any brand exceeds ~10M clicks/month.
REPORTING_BACKEND = os.environ.get('REPORTING_BACKEND', 'postgres')

GEOIP_COUNTRY_DB = os.environ.get(
    'GEOIP_COUNTRY_DB',
    '/opt/nexora-platform/data/geoip/GeoLite2-Country.mmdb',
)
GEOIP_CITY_DB = os.environ.get(
    'GEOIP_CITY_DB',
    '/opt/nexora-platform/data/geoip/GeoLite2-City.mmdb',
)

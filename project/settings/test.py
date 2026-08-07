"""Settings for the test suite.

Point pytest at this and the suite stops depending on whatever environment
happens to be loaded. That dependency was not theoretical: running the suite
the documented way — `docker run --env-file /opt/nexora-platform/.env.prod` —
produced 8 red tests across three files that had nothing wrong with them.

    leadgen/tests/test_api_doc_brand_scoping.py   1
    payouts/tests/test_brand_scope.py             4
    payouts/tests/test_controls.py                3

All of them DisallowedHost. base.py defaults DJANGO_ALLOWED_HOSTS to '*', so a
bare checkout is fine; .env.prod SETS it to the real domains, so every test
that drives a brand host (a.test, cpa.nexora.test) got rejected by Django's
host validation before reaching a view. Nothing to do with the code under test.

Eight permanently-red tests is worse than none. It trains everyone to read a
failure summary and conclude "those are the usual ones", which is exactly how a
real regression gets waved through.

Usage — pytest.ini already sets DJANGO_SETTINGS_MODULE to this module, so:

    pytest

DATABASE_URL / REDIS_URL / TRACKER_URL are still read from the environment
(base.py requires them, and the test database is created on a real Postgres),
but each has a working default here so a bare `pytest` against a local stack
does not need an env file at all.
"""
import os
import tempfile

# base.py reads these at import time via os.environ[...] and raises KeyError if
# absent, so they must be seeded BEFORE the star-import below. Defaults only —
# a real value in the environment always wins, which is what lets the same
# module work against a local Postgres and against the shared one.
os.environ.setdefault('DATABASE_URL', 'postgres://cloudtrade:cloudtrade@localhost:5432/cloudtrade_main')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/1')
os.environ.setdefault('TRACKER_URL', 'http://localhost:8000')

from .base import *  # noqa: E402,F403

# base.py does not define SECRET_KEY — prod.py does, from the environment.
# Importing base alone therefore leaves it empty and Django raises
# ImproperlyConfigured on first access. Set here rather than read from the
# environment so a test run can never depend on, or accidentally exercise, the
# production key: nexora.crypto derives its Fernet key from SECRET_KEY, and
# tests that encrypt should not be producing values the live key can read.
SECRET_KEY = 'test-only-not-a-real-secret-and-never-used-outside-pytest'

# --- the actual fix -----------------------------------------------------------
#
# '*' rather than a list, matching base.py's own default. That default is what
# a bare checkout runs under and what every existing test was written against;
# .env.prod narrowing it is the whole bug this module exists to neutralise.
#
# I first tried an explicit list and it was worse — 15 failures instead of 8,
# because brand fixtures mint their own domains (a.test, b.test, cb.test,
# ob.test, and more as tests are added). Host validation is a PRODUCTION
# concern; these tests assert brand RESOLUTION (brands/middleware.py maps host
# -> Brand), which is a different thing. Making people edit settings to add a
# fixture would be a tax with no safety bought.
ALLOWED_HOSTS = ['*']

# Cannot be derived from ALLOWED_HOSTS now that it is '*' — 'http://*' is not a
# valid origin. Django only consults this for unsafe cross-origin requests; the
# test client's default host covers what the suite actually drives.
CSRF_TRUSTED_ORIGINS = ['http://testserver', 'http://localhost', 'http://127.0.0.1']

# Keep generated files out of the working tree. billing.tasks.invoice writes
# invoice PDFs under MEDIA_ROOT, and with the default (BASE_DIR/media) a test
# run left an untracked media/ directory in the repo — noise in git status, and
# one careless `git add .` from being committed.
MEDIA_ROOT = tempfile.mkdtemp(prefix='nexora-test-media-')

# The suite creates a lot of users. The real hasher is deliberately slow, which
# is right in production and pure waiting here.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Locmem, so a test run cannot read or evict entries in a shared Redis — the
# same instance production uses. Tests that assert on caching still work; they
# just get their own cache.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'nexora-test',
    }
}

# Never send mail from a test run.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# DELIBERATELY NOT SET: CELERY_TASK_ALWAYS_EAGER.
#
# It looks like the obvious safety net — run tasks inline so a stray .delay()
# cannot reach a real worker — and it breaks this suite badly. Tasks here fire
# from model signals with payloads the fixtures do not fully populate:
# creating a Conversion dispatches postback.tasks.send_postback, which opens
# with `assert bool(conversion['offer_id'])`. Under eager execution that runs
# inline and, with EAGER_PROPAGATES, raises straight into whatever test merely
# wanted a Conversion row. It cost 10 passing tests before I backed it out.
#
# The underlying worry is real and unaddressed: with .env.prod loaded, the
# broker is PRODUCTION Redis, so a stray .delay() in a test genuinely can
# enqueue work for the live worker. The right fix is a separate broker for
# tests, not changing when tasks execute — that changes the behaviour under
# test. Tracked rather than papered over.

DEBUG = False

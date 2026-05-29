import redis
from django.conf import settings
from django.db import connection, OperationalError
from django.http import JsonResponse


def healthz(request):
    checks = {}

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks['db'] = 'ok'
    except OperationalError:
        checks['db'] = 'error'

    try:
        r = redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.ping()
        r.close()
        checks['redis'] = 'ok'
    except Exception:
        checks['redis'] = 'error'

    checks['status'] = 'ok' if all(v == 'ok' for v in checks.values()) else 'error'
    return JsonResponse(checks, status=200 if checks['status'] == 'ok' else 503)

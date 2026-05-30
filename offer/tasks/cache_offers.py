import json
import redis
from project._celery import _celery
from project.redis_conn import pool
from ..models import Offer


@_celery.task
def cache_offers():
    redis_conn = redis.Redis(connection_pool=pool)
    for offer in Offer.objects.select_related('mmp').all():
        record = {
            'tracking_link': offer.tracking_link,
            'mmp_vendor': offer.mmp.vendor if offer.mmp else None,
            'mmp_click_template': offer.mmp.click_template if offer.mmp else None,
            'mmp_app_id': offer.mmp_app_id,
            'affiliate_id': None,  # populated per-click in the view
        }
        redis_conn.set(f'offers:{offer.id}', json.dumps(record))

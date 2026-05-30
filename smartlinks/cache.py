import json
from typing import Dict, Optional

import redis

from project.redis_conn import pool


class SmartLinksCache:

    @staticmethod
    def get(alias: str) -> Optional[Dict]:
        redis_conn = redis.Redis(connection_pool=pool)
        raw = redis_conn.get(f'smartlinks:{alias}')
        if raw:
            return json.loads(raw)
        return None

    @staticmethod
    def set_all() -> None:
        from smartlinks.models import SmartLink
        redis_conn = redis.Redis(connection_pool=pool)
        for sl in SmartLink.objects.prefetch_related('rules').all():
            record = {
                'id': sl.id,
                'name': sl.name,
                'alias': sl.alias,
                'default_url': sl.default_url,
                'is_active': sl.is_active,
                'rules': [
                    {
                        'priority': r.priority,
                        'destination_url': r.destination_url,
                        'countries': r.countries,
                        'device_type': r.device_type,
                        'is_active': r.is_active,
                    }
                    for r in sl.rules.filter(is_active=True).order_by('priority')
                ],
            }
            redis_conn.set(f'smartlinks:{sl.alias}', json.dumps(record))

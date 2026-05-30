from project._celery import _celery
from smartlinks.cache import SmartLinksCache


@_celery.task
def cache_smart_links():
    SmartLinksCache.set_all()

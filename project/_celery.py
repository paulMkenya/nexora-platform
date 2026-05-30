import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

from django.conf import settings  # noqa


_celery = Celery(
    'nexora',
    broker=settings.REDIS_URL
)

_celery.config_from_object('django.conf:settings', namespace='CELERY')

_celery.autodiscover_tasks()

# task_routes = {
#     'campaigns.tasks.stats.push_sent': {'queue': 'stats:pushes'},
#     'tracker.tasks.stats.*': {'queue': 'stats'},
# }

_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],  # Ignore other content
    timezone='Europe/Moscow',
    # task_routes=task_routes,
)

_celery.conf.beat_schedule = {
    'cache-offers': {
        'task': 'offer.tasks.cache_offers.cache_offers',
        'schedule': 60,
    },
    'cache-smart-links': {
        'task': 'smartlinks.tasks.cache.cache_smart_links',
        'schedule': 60,
    },
    'generate-monthly-invoices': {
        'task': 'billing.tasks.invoice.generate_monthly_invoices',
        'schedule': crontab(minute=5, hour=0, day_of_month=1),
    },
}

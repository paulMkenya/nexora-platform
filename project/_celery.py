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

# Every module that defines a task but that autodiscover_tasks() does NOT reach.
#
# autodiscover_tasks() imports `<app>.tasks` and nothing else. That works for an
# app whose tasks live in a tasks.py, and for offer/, whose tasks/__init__.py
# re-exports its submodule. It does NOT work for an app whose tasks/ package has
# an empty __init__.py (billing, payouts, smartlinks, postback, tracker) or for
# a task defined outside the tasks path entirely
# (leadgen/postback_delivery.py).
#
# Those tasks were registering only by ACCIDENT — when some unrelated import
# chain at startup happened to pull the module in (a view importing its own
# task, say). Anything with no such chain silently never registered, and the
# worker answered every send with "Received unregistered task of type ...",
# discarded the message, and moved on. No retry, no dead-letter, no alert: the
# work simply never happened. That is how affiliate postbacks, monthly invoice
# generation, payout-request generation and the smart-link cache refresh were
# all dead in production while looking perfectly healthy from the sending side.
#
# Listing them explicitly makes registration a property of THIS file rather
# than of import order. Add a module here when you add a task outside a
# tasks.py — project/tests/test_celery_registration.py fails if you forget.
_celery.conf.imports = (
    'billing.tasks.debit',
    'billing.tasks.invoice',
    'billing.tasks.topup',
    'leadgen.postback_delivery',
    'payouts.tasks.generate',
    'payouts.tasks.ipn',
    'postback.tasks.send_postback',
    'smartlinks.tasks.cache',
    'smartlinks.tasks.click',
    'tracker.tasks.click',
    'tracker.tasks.conversion',
    'tracker.tasks.sync',
)

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
    'generate-payout-requests': {
        'task': 'payouts.tasks.generate.generate_payout_requests',
        'schedule': crontab(minute=30, hour=2),
    },
    'refresh-reporting-views': {
        'task': 'reporting.tasks.refresh_reporting_views',
        'schedule': 300,  # every 5 minutes
    },
    'mark-dormant-leads': {
        'task': 'leads.tasks.mark_dormant_leads',
        'schedule': crontab(minute=0, hour=3),  # daily at 03:00
    },
    'sync-leadgen-buyer-statuses': {
        'task': 'leadgen.tasks.sync_buyer_statuses',
        'schedule': 1800,  # every 30 minutes
    },
}

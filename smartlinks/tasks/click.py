from django.contrib.auth import get_user_model

from project._celery import _celery
from smartlinks.models import SmartLinkClick


@_celery.task
def smart_link_click(data):
    click = SmartLinkClick()
    click.id = data['click_id']
    click.smart_link_id = data['smart_link_id']
    click.ip = data.get('ip') or None
    click.country = data.get('country', '')
    click.ua = (data.get('ua', '') or '')[:200]
    click.device_type = data.get('device_type', '')
    click.destination_url = data.get('destination_url', '')
    click.sub1 = data.get('sub1', '')
    click.sub2 = data.get('sub2', '')

    pid = data.get('pid')
    if pid:
        try:
            click.affiliate = get_user_model().objects.get(pk=int(pid))
        except Exception:
            pass

    click.save()
    return f'SmartLinkClick: {click.id}'

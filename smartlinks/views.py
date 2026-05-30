import uuid

from django.http import Http404, HttpResponse
from django.shortcuts import redirect

from ext.device import device_type as get_device_type
from ext.geoip import country_code as get_country
from smartlinks.cache import SmartLinksCache
from smartlinks.router import resolve_url
from smartlinks.tasks.click import smart_link_click
from tracker.views import get_client_ip


def smart_link(request, alias: str):
    data = SmartLinksCache.get(alias)
    if not data:
        raise Http404

    if not data.get('is_active'):
        raise Http404

    ip = get_client_ip(request)
    ua = request.META.get('HTTP_USER_AGENT', '')
    country = get_country(ip)
    device = get_device_type(ua)

    destination = resolve_url(data['rules'], country, device)
    if not destination:
        destination = data['default_url']

    if not destination:
        return HttpResponse('No destination configured', status=503)

    pid = request.GET.get('pid', '')
    if pid:
        smart_link_click.delay({
            'click_id': uuid.uuid4().hex,
            'smart_link_id': data['id'],
            'pid': pid,
            'ip': ip,
            'ua': ua,
            'country': country,
            'device_type': device,
            'destination_url': destination,
            'sub1': request.GET.get('sub1', ''),
            'sub2': request.GET.get('sub2', ''),
        })

    return redirect(destination)

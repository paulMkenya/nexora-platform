from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from mmp.models import MMP, MMPCallback, VENDOR_CHOICES


_VALID_VENDORS = {v for v, _ in VENDOR_CHOICES}


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mmp_callback(request, vendor):
    """
    Receive an inbound postback from an MMP vendor.
    Accepts both GET (query-string) and POST (form-body or query-string).
    Idempotent on (click_id, event_name): duplicate callbacks return 200 without
    creating a second conversion.
    """
    if vendor not in _VALID_VENDORS:
        return HttpResponse(f'Unknown vendor: {vendor}', status=404)

    try:
        mmp = MMP.objects.get(vendor=vendor)
    except MMP.DoesNotExist:
        return HttpResponse(f'MMP not configured: {vendor}', status=404)

    patterns = mmp.callback_patterns
    click_id_param = patterns.get('click_id_param', 'click_id')
    event_name_param = patterns.get('event_name_param', 'event_name')

    # Read params from query string first, then POST body as fallback
    params = request.GET
    click_id = params.get(click_id_param, '').strip()
    if not click_id and request.method == 'POST':
        click_id = request.POST.get(click_id_param, '').strip()
    event_name = (params.get(event_name_param) or request.POST.get(event_name_param, 'install')).strip()

    if not click_id:
        return HttpResponse('Missing click_id', status=400)

    raw_data = {**dict(request.GET), **dict(request.POST)}

    # Resolve offer from the tracker Click row (best-effort)
    offer = None
    try:
        from tracker.models import Click
        click_obj = Click.objects.select_related('offer').get(pk=click_id)
        offer = click_obj.offer
    except Exception:
        pass

    callback, created = MMPCallback.objects.get_or_create(
        click_id=click_id,
        event_name=event_name,
        defaults={
            'vendor': vendor,
            'offer': offer,
            'raw_data': raw_data,
        },
    )

    if created and not callback.processed:
        _process_callback(callback, offer)

    return HttpResponse('OK')


def _process_callback(callback: MMPCallback, offer):
    """Queue a conversion task for a newly received MMP callback."""
    try:
        from tracker.tasks.conversion import conversion as conversion_task
        data = {
            'click_id': callback.click_id,
            'goal': callback.event_name,
            'sum': 0.0,
            'status': 'approved',
        }
        conversion_task.delay(data)
        callback.processed = True
        callback.save(update_fields=['processed'])
    except Exception:
        pass

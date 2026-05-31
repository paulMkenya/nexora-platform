from django.db.models import Q


class BrandMiddleware:
    """Resolve request.host → Brand, fallback to default brand."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_host = request.META.get('HTTP_HOST', '')
        host = raw_host.split(':')[0].lower()
        from brands.models import Brand
        brand = Brand.objects.filter(
            Q(primary_domain__iexact=host) | Q(tracking_domain__iexact=host)
        ).first()
        if brand is None:
            brand = Brand.get_default()
        request.brand = brand
        return self.get_response(request)

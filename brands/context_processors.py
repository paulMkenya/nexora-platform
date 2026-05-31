def brand_context(request):
    brand = getattr(request, 'brand', None)
    if brand is None:
        from brands.models import Brand
        brand = Brand.get_default()
    return {'brand': brand}

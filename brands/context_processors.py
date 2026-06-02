def brand_context(request):
    brand = getattr(request, 'brand', None)
    if brand is None:
        from brands.models import Brand
        brand = Brand.get_default()
    return {'brand': brand}


def operator_roles(request):
    """Role flags for the shared operator nav, so each role sees only its tools."""
    from brands.scoping import (
        is_affiliate_manager,
        is_brand_admin,
        is_platform_owner,
    )

    user = getattr(request, 'user', None)
    return {
        'is_platform_owner': is_platform_owner(user),
        'is_brand_admin': is_brand_admin(user),
        'is_affiliate_manager': is_affiliate_manager(user),
    }

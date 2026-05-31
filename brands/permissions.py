from functools import wraps
from django.core.exceptions import PermissionDenied


def brand_required(field='brand'):
    """Decorator: raise PermissionDenied if obj.brand != request.brand."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def assert_same_brand(request, obj):
    """Raise PermissionDenied if obj.brand differs from request.brand."""
    obj_brand = getattr(obj, 'brand_id', None)
    req_brand = getattr(request.brand, 'pk', None)
    if obj_brand is not None and req_brand is not None and obj_brand != req_brand:
        raise PermissionDenied

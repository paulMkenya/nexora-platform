import re

from django.utils.text import slugify

from brands.links import tracking_base_url
from shortlinks.models import ShortLink

# Words that read like platform paths; refusing them keeps links unambiguous.
RESERVED = {'admin', 'api', 'click', 'postback', 'login', 'partner', 'advertiser', 'go', 'sl'}


def short_url(link, request=None):
    """Public URL of a short link, on the offer's brand tracking domain."""
    base = tracking_base_url(brand=getattr(link.offer, 'brand', None), request=request)
    return f'{base}/go/{link.slug}'


def normalize_slug(value):
    slug = slugify(value or '')[:64].strip('-')
    return re.sub(r'-{2,}', '-', slug)


def suggest_slug(affiliate, offer):
    """A readable, unused slug: '<affiliate>-<offer title>', numbered if taken."""
    base = normalize_slug(f'{affiliate.username.split("@")[0]}-{offer.title}')[:58].strip('-')
    if len(base) < 3:
        base = f'offer-{offer.id}'
    slug, n = base, 2
    while ShortLink.objects.filter(slug=slug).exists() or slug in RESERVED:
        slug, n = f'{base}-{n}', n + 1
    return slug


def slug_error(slug, exclude_pk=None):
    """Return a user-facing error for an unusable slug, or ''."""
    from django.core.exceptions import ValidationError
    from shortlinks.models import slug_validator

    try:
        slug_validator(slug)
    except ValidationError as exc:
        return exc.messages[0]
    if slug in RESERVED:
        return f'"{slug}" is reserved. Pick another name.'
    taken = ShortLink.objects.filter(slug=slug)
    if exclude_pk:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        return f'"{slug}" is already taken. Pick another name.'
    return ''

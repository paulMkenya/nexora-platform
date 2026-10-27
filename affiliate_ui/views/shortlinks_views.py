"""Affiliate self-service short links: clean /go/<name> URLs for their offers.

Only offers the affiliate may currently send to (``offers_for_affiliate``) can
be linked, and every write is scoped to ``affiliate=request.user``."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from affiliate_ui.views.general_views import offers_for_affiliate
from impersonation.decorators import block_when_impersonating
from shortlinks.models import ShortLink
from shortlinks.services import normalize_slug, short_url, slug_error, suggest_slug

SUB_FIELDS = ('sub1', 'sub2', 'sub3', 'sub4', 'sub5')


@require_approved_affiliate
def short_links(request):
    links = list(ShortLink.objects.filter(affiliate=request.user).select_related('offer__brand'))
    for link in links:
        link.url = short_url(link, request=request)
    offers = offers_for_affiliate(request.user).order_by('title')
    selected = request.GET.get('offer', '')
    suggestion = ''
    if selected.isdigit():
        offer = offers.filter(pk=selected).first()
        if offer:
            suggestion = suggest_slug(request.user, offer)
    return render(request, 'affiliate_ui/short_links.html', {
        'links': links,
        'offers': offers,
        'selected_offer': selected,
        'suggestion': suggestion,
        'sub_fields': SUB_FIELDS,
    })


@block_when_impersonating
@require_approved_affiliate
@require_POST
def short_link_create(request):
    offer_id = request.POST.get('offer', '')
    offer = offers_for_affiliate(request.user).filter(pk=offer_id).first() if offer_id.isdigit() else None
    if offer is None:
        messages.error(request, 'Pick one of your available offers.')
        return redirect('affiliate_ui:short_links')

    raw = request.POST.get('slug', '')
    slug = normalize_slug(raw) if raw.strip() else suggest_slug(request.user, offer)
    error = slug_error(slug)
    if error:
        messages.error(request, error)
        return redirect(f"{reverse('affiliate_ui:short_links')}?offer={offer.id}")

    link = ShortLink.objects.create(
        slug=slug, affiliate=request.user, offer=offer,
        label=(request.POST.get('label') or '').strip()[:128],
        **{f: (request.POST.get(f) or '').strip()[:500] for f in SUB_FIELDS},
    )
    messages.success(request, f'Short link ready: <code>{short_url(link, request=request)}</code>')
    return redirect('affiliate_ui:short_links')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def short_link_update(request, pk):
    link = get_object_or_404(ShortLink, pk=pk, affiliate=request.user)
    slug = normalize_slug(request.POST.get('slug', ''))
    error = slug_error(slug, exclude_pk=link.pk)
    if error:
        messages.error(request, error)
        return redirect('affiliate_ui:short_links')
    link.slug = slug
    link.label = (request.POST.get('label') or '').strip()[:128]
    for f in SUB_FIELDS:
        setattr(link, f, (request.POST.get(f) or '').strip()[:500])
    link.save()
    messages.success(request, 'Short link updated. The old address no longer works if you renamed it.')
    return redirect('affiliate_ui:short_links')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def short_link_toggle_active(request, pk):
    link = get_object_or_404(ShortLink, pk=pk, affiliate=request.user)
    link.is_active = not link.is_active
    link.save(update_fields=['is_active'])
    messages.success(request, f'Short link {"enabled" if link.is_active else "disabled"}.')
    return redirect('affiliate_ui:short_links')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def short_link_delete(request, pk):
    get_object_or_404(ShortLink, pk=pk, affiliate=request.user).delete()
    messages.success(request, 'Short link deleted.')
    return redirect('affiliate_ui:short_links')

import datetime
from collections import defaultdict

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from brands.models import Brand
from brands.permissions import brand_admin_required, platform_owner_required
from brands.scoping import operator_brand


_BRAND_FORM_FIELDS = (
    'name', 'slug', 'primary_domain', 'tracking_domain', 'support_email',
    'logo', 'favicon', 'terms_url', 'privacy_url', 'primary_color',
    'secondary_color', 'is_default',
)


def _form_data(request, brand=None):
    """Return the ``post`` mapping that brand_form.html prefills inputs from.

    The template reads every field via ``post.<field>``. Two hazards are handled
    here:

    1. A missing template variable used as a *filter argument* raises
       VariableDoesNotExist (it is not swallowed like a missing top-level
       variable), so ``post`` must resolve for every field on every render path.
       A ``defaultdict(str)`` yields '' for any field not present.
    2. The form must NOT prefill from the global ``brand`` template variable —
       that is the *request's* brand injected by brands.context_processors and
       would leak the current brand's data onto the create form. Prefill is
       driven solely by this dict: seeded from the edited ``brand`` on GET, and
       overridden by the submitted values on a POST re-render.
    """
    data = defaultdict(str)
    if brand is not None:
        for field in _BRAND_FORM_FIELDS:
            data[field] = getattr(brand, field)
    if request.method == 'POST':
        data.update(request.POST.dict())
    return data


@staff_member_required
def dashboard(request):
    """Unified network-admin home with nav cards + at-a-glance stats.

    All counts are brand-scoped to request.brand for ordinary operators; a
    superuser (platform owner) sees network-wide totals across every brand and
    the page shows an "all brands" indicator.
    """
    from user_profile.models import Profile
    from payouts.models import PayoutRequest, STATUS_PENDING
    from tracker.models import Conversion
    from brands.scoping import scope_brand, sees_all_brands

    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)

    affiliate_qs = Profile.objects.filter(role=Profile.Role.AFFILIATE)
    payout_qs = PayoutRequest.objects.filter(status=STATUS_PENDING)
    since = timezone.now() - datetime.timedelta(hours=24)
    conv_qs = Conversion.objects.filter(created_at__gte=since, fraud_score__gt=0)

    if not show_all_brands:
        affiliate_qs = affiliate_qs.filter(brand=brand)
        payout_qs = payout_qs.filter(affiliate__profile__brand=brand)
        conv_qs = conv_qs.filter(brand=brand)

    pending_affiliates = affiliate_qs.filter(
        affiliate_status=Profile.AffiliateStatus.PENDING
    ).count()
    pending_payouts = payout_qs.count()
    flagged_conversions = conv_qs.count()

    ctx = {
        'active': 'dashboard',
        'pending_affiliates': pending_affiliates,
        'pending_payouts': pending_payouts,
        'flagged_conversions': flagged_conversions,
        'show_all_brands': show_all_brands,
    }
    return render(request, 'admin_shared/dashboard.html', ctx)


@platform_owner_required
def brand_list(request):
    brands = Brand.objects.all()
    return render(request, 'brands/admin/brand_list.html', {'brands': brands})


def _validate_new_brand(slug, name, primary_domain, tracking_domain):
    errors = []
    if not slug:
        errors.append('Slug is required.')
    if not name:
        errors.append('Name is required.')
    if not primary_domain:
        errors.append('Primary domain is required.')
    if not tracking_domain:
        errors.append('Tracking domain is required.')
    if slug and Brand.objects.filter(slug=slug).exists():
        errors.append(f'Slug "{slug}" is already taken.')
    if primary_domain and Brand.objects.filter(primary_domain=primary_domain).exists():
        errors.append(f'Primary domain "{primary_domain}" is already registered.')
    if tracking_domain and Brand.objects.filter(tracking_domain=tracking_domain).exists():
        errors.append(f'Tracking domain "{tracking_domain}" is already registered.')
    return errors


@platform_owner_required
@require_http_methods(['GET', 'POST'])
def brand_create(request):
    if request.method == 'POST':
        slug = request.POST.get('slug', '').strip()
        name = request.POST.get('name', '').strip()
        primary_domain = request.POST.get('primary_domain', '').strip()
        tracking_domain = request.POST.get('tracking_domain', '').strip()
        errors = _validate_new_brand(slug, name, primary_domain, tracking_domain)
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'brands/admin/brand_form.html', {
                'action': 'Create', 'post': _form_data(request),
            })
        brand = Brand.objects.create(
            slug=slug,
            name=name,
            primary_domain=primary_domain,
            tracking_domain=tracking_domain,
            primary_color=request.POST.get('primary_color', '#6366f1').strip(),
            secondary_color=request.POST.get('secondary_color', '#4f46e5').strip(),
            support_email=request.POST.get('support_email', '').strip(),
            logo=request.POST.get('logo', '').strip(),
            favicon=request.POST.get('favicon', '').strip(),
            terms_url=request.POST.get('terms_url', '').strip(),
            privacy_url=request.POST.get('privacy_url', '').strip(),
            is_default=request.POST.get('is_default') == 'on',
        )
        messages.success(request, f'Brand "{brand.name}" created successfully.')
        return redirect('brands_admin:brand_setup', pk=brand.pk)

    return render(request, 'brands/admin/brand_form.html', {
        'action': 'Create', 'post': _form_data(request),
    })


@platform_owner_required
@require_http_methods(['GET', 'POST'])
def brand_edit(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        brand.name = request.POST.get('name', brand.name).strip()
        brand.primary_domain = request.POST.get('primary_domain', brand.primary_domain).strip()
        brand.tracking_domain = request.POST.get('tracking_domain', brand.tracking_domain).strip()
        brand.primary_color = request.POST.get('primary_color', brand.primary_color).strip()
        brand.secondary_color = request.POST.get('secondary_color', brand.secondary_color).strip()
        brand.support_email = request.POST.get('support_email', brand.support_email).strip()
        brand.logo = request.POST.get('logo', brand.logo).strip()
        brand.favicon = request.POST.get('favicon', brand.favicon).strip()
        brand.terms_url = request.POST.get('terms_url', brand.terms_url).strip()
        brand.privacy_url = request.POST.get('privacy_url', brand.privacy_url).strip()
        brand.is_default = request.POST.get('is_default') == 'on'
        brand.save()
        messages.success(request, f'Brand "{brand.name}" updated.')
        return redirect('brands_admin:brand_list')

    return render(request, 'brands/admin/brand_form.html', {
        'action': 'Edit', 'post': _form_data(request, brand),
    })


@platform_owner_required
@require_http_methods(['POST'])
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if brand.is_default:
        messages.error(request, 'Cannot delete the default brand.')
        return redirect('brands_admin:brand_list')
    name = brand.name
    brand.delete()
    messages.success(request, f'Brand "{name}" deleted.')
    return redirect('brands_admin:brand_list')


@platform_owner_required
def brand_setup(request, pk):
    """Show operator setup instructions after brand creation."""
    brand = get_object_or_404(Brand, pk=pk)
    return render(request, 'brands/admin/brand_setup.html', {'brand': brand})


@brand_admin_required
@require_http_methods(['GET', 'POST'])
def brand_email_settings(request):
    """Per-brand outbound SMTP settings.

    A brand admin edits their *own* brand; the platform owner edits the brand of
    the host they're on. The SMTP password is write-only — it's stored encrypted
    and never rendered back, so leaving it blank on save keeps the current one.
    """
    brand = operator_brand(request.user) or getattr(request, 'brand', None)
    if brand is None:
        messages.error(request, 'No brand is associated with your account.')
        return redirect('/admin/dashboard/')

    if request.method == 'POST':
        brand.smtp_host = request.POST.get('smtp_host', '').strip()
        try:
            brand.smtp_port = int(request.POST.get('smtp_port') or 587)
        except ValueError:
            brand.smtp_port = 587
        brand.smtp_username = request.POST.get('smtp_username', '').strip()
        brand.smtp_use_tls = request.POST.get('smtp_use_tls') == 'on'
        brand.smtp_from_email = request.POST.get('smtp_from_email', '').strip()
        new_password = request.POST.get('smtp_password', '')
        if new_password:
            brand.set_smtp_password(new_password)
        brand.save()
        messages.success(request, 'Email settings saved.')
        return redirect('brands_admin:email_settings')

    return render(request, 'brands/admin/email_settings.html', {
        'brand': brand,
        'active': 'email_settings',
        'has_password': bool(brand.smtp_password_encrypted),
    })

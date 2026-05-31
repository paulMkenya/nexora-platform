"""Network-admin views for affiliate management at /admin/affiliates/."""
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from user_profile.models import Profile

logger = logging.getLogger(__name__)

User = get_user_model()


def _require_network_admin(view_func):
    @login_required
    def _wrapped(request, *args, **kwargs):
        try:
            role = request.user.profile.role
        except Exception:
            role = None
        if role not in (Profile.Role.NETWORK_ADMIN, Profile.Role.AFFILIATE_MANAGER) and not request.user.is_superuser:
            return render(request, 'affiliate_ui/403.html', status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


def _notify_approved(request, user):
    brand = getattr(request, 'brand', None)
    brand_name = brand.name if brand else 'Nexora'
    host = (brand.primary_domain if brand else None) or request.META.get('HTTP_HOST', 'localhost')
    subject = f'Your {brand_name} account has been approved!'
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Great news — your affiliate account on {brand_name} has been approved.\n\n'
        f'Log in at: https://{host}/partner/login/\n'
    )
    try:
        send_mail(subject, body, None, [user.email], fail_silently=False)
    except Exception:
        logger.warning('SMTP not configured — approved notification for %s', user.email)


@_require_network_admin
def affiliate_list(request):
    brand = getattr(request, 'brand', None)
    qs = Profile.objects.select_related('user').filter(role=Profile.Role.AFFILIATE)
    if brand:
        qs = qs.filter(brand=brand)

    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(affiliate_status=status_filter)

    return render(request, 'affiliate_ui/admin_affiliates.html', {
        'profiles': qs,
        'status_filter': status_filter,
        'status_choices': Profile.AffiliateStatus.choices,
    })


@_require_network_admin
@require_POST
def affiliate_approve(request, pk):
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        pk=pk,
        role=Profile.Role.AFFILIATE,
        brand=getattr(request, 'brand', None),
    )
    profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    profile.save(update_fields=['affiliate_status'])
    _notify_approved(request, profile.user)
    return redirect('/admin/affiliates/')


@_require_network_admin
@require_POST
def affiliate_reject(request, pk):
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        pk=pk,
        role=Profile.Role.AFFILIATE,
        brand=getattr(request, 'brand', None),
    )
    profile.affiliate_status = Profile.AffiliateStatus.REJECTED
    profile.save(update_fields=['affiliate_status'])
    return redirect('/admin/affiliates/')


@_require_network_admin
@require_POST
def affiliate_suspend(request, pk):
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        pk=pk,
        role=Profile.Role.AFFILIATE,
        brand=getattr(request, 'brand', None),
    )
    profile.affiliate_status = Profile.AffiliateStatus.SUSPENDED
    profile.save(update_fields=['affiliate_status'])
    return redirect('/admin/affiliates/')

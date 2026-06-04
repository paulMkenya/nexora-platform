"""Advertiser self-registration, email verification, and brand-aware login.

Mirrors ``affiliate_ui.views.registration_views``. A self-registered advertiser
is created PENDING + unverified, stamped with the brand whose domain they
registered on, auto-logged-in, and dropped on their dashboard in a pending
state until a brand admin approves them and they verify their email.
"""
import logging

from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView
from django.core import signing
from django.shortcuts import redirect, render

from advertiser_ui.forms import AdvertiserRegistrationForm
from brands.email import send_brand_mail
from offer.models import Advertiser
from user_profile.models import Profile

logger = logging.getLogger(__name__)

User = get_user_model()

_EMAIL_SALT = 'advertiser-email-verify'
_TOKEN_MAX_AGE = 86400  # 24 hours


def _make_token(user_pk: int) -> str:
    return signing.dumps({'uid': user_pk}, salt=_EMAIL_SALT)


def _verify_token(token: str):
    """Returns user pk on success, None on invalid/expired."""
    try:
        data = signing.loads(token, max_age=_TOKEN_MAX_AGE, salt=_EMAIL_SALT)
        return data['uid']
    except (signing.BadSignature, signing.SignatureExpired, KeyError):
        return None


def _send_verification_email(request, user, token):
    scheme = 'https' if request.is_secure() else 'http'
    brand = getattr(request, 'brand', None)
    host = (brand.primary_domain if brand else None) or request.META.get('HTTP_HOST', 'localhost')
    verify_url = f'{scheme}://{host}/advertiser/verify-email/{token}/'
    subject = f'Verify your email – {brand.name if brand else "Nexora"}'
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Click the link below to verify your advertiser account email address:\n\n'
        f'{verify_url}\n\n'
        f'This link expires in 24 hours.\n'
    )
    try:
        send_brand_mail(brand, subject, body, [user.email], fail_silently=False)
    except Exception:
        logger.warning('SMTP not configured — verification URL: %s', verify_url)


def register(request):
    if request.user.is_authenticated:
        return redirect('/advertiser/')

    if request.method == 'POST':
        form = AdvertiserRegistrationForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            username = d['email'].lower()
            first_name = d['contact_name'].strip()
            user = User.objects.create_user(
                username=username,
                email=d['email'].lower(),
                password=d['password1'],
                first_name=first_name,
            )
            brand = getattr(request, 'brand', None)
            country = (d.get('country') or '').upper()

            # Signal already created the Profile; mark it ADVERTISER + brand.
            profile = user.profile
            profile.role = Profile.Role.ADVERTISER
            profile.brand = brand
            profile.country = country
            profile.save(update_fields=['role', 'brand', 'country'])

            # The advertiser record carries the onboarding state.
            Advertiser.objects.create(
                user=user,
                brand=brand,
                company=d['company'],
                email=d['email'].lower(),
                contact_person=first_name,
                site=d.get('website') or '',
                comment=(f"Vertical: {d['vertical']}" if d.get('vertical') else ''),
                country=country,
                advertiser_status=Advertiser.AdvertiserStatus.PENDING,
                email_verified=False,
            )

            token = _make_token(user.pk)
            _send_verification_email(request, user, token)
            login(request, user)
            return redirect('/advertiser/')
    else:
        form = AdvertiserRegistrationForm()

    return render(request, 'advertiser_ui/register.html', {'form': form})


def verify_email(request, token: str):
    uid = _verify_token(token)
    if uid is None:
        return render(request, 'advertiser_ui/verify_email_result.html', {'success': False})

    try:
        user = User.objects.get(pk=uid)
        adv = user.advertiser_profile
        if not adv.email_verified:
            adv.email_verified = True
            adv.save(update_fields=['email_verified'])
    except (User.DoesNotExist, Advertiser.DoesNotExist):
        return render(request, 'advertiser_ui/verify_email_result.html', {'success': False})

    return render(request, 'advertiser_ui/verify_email_result.html', {'success': True})


class AdvertiserLoginView(LoginView):
    """Brand-aware advertiser login (parallel to AffiliateLoginView)."""
    template_name = 'advertiser_ui/login.html'
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return '/advertiser/'

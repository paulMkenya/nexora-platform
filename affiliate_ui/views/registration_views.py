"""Affiliate self-registration and email verification."""
import logging

from django.contrib.auth import get_user_model, login
from django.core import signing
from django.core.mail import send_mail
from django.shortcuts import redirect, render

from affiliate_ui.forms import AffiliateRegistrationForm
from user_profile.models import Profile

logger = logging.getLogger(__name__)

User = get_user_model()

_EMAIL_SALT = 'affiliate-email-verify'
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
    verify_url = f'{scheme}://{host}/partner/verify-email/{token}/'
    subject = f'Verify your email – {request.brand.name if request.brand else "Nexora"}'
    body = (
        f'Hi {user.first_name or user.username},\n\n'
        f'Click the link below to verify your email address:\n\n'
        f'{verify_url}\n\n'
        f'This link expires in 24 hours.\n'
    )
    try:
        send_mail(subject, body, None, [user.email], fail_silently=False)
    except Exception:
        logger.warning('SMTP not configured — verification URL: %s', verify_url)


def register(request):
    if request.user.is_authenticated:
        return redirect('/partner/')

    if request.method == 'POST':
        form = AffiliateRegistrationForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            username = d['email'].lower()
            user = User.objects.create_user(
                username=username,
                email=d['email'].lower(),
                password=d['password1'],
                first_name=d['first_name'],
                last_name=d['last_name'],
            )
            brand = getattr(request, 'brand', None)
            # Signal already created the Profile; update it with registration data.
            profile = user.profile
            profile.role = Profile.Role.AFFILIATE
            profile.affiliate_status = Profile.AffiliateStatus.PENDING
            profile.email_verified = False
            profile.brand = brand
            profile.save(update_fields=['role', 'affiliate_status', 'email_verified', 'brand'])
            token = _make_token(user.pk)
            _send_verification_email(request, user, token)
            login(request, user)
            return redirect('/partner/dashboard/')
    else:
        form = AffiliateRegistrationForm()

    return render(request, 'affiliate_ui/register.html', {'form': form})


def verify_email(request, token: str):
    uid = _verify_token(token)
    if uid is None:
        return render(request, 'affiliate_ui/verify_email_result.html', {'success': False})

    try:
        user = User.objects.get(pk=uid)
        profile = user.profile
        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])
    except (User.DoesNotExist, Profile.DoesNotExist):
        return render(request, 'affiliate_ui/verify_email_result.html', {'success': False})

    return render(request, 'affiliate_ui/verify_email_result.html', {'success': True})

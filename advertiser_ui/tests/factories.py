"""Shared test factory helpers for advertiser_ui tests."""
from decimal import Decimal

from offer.models import Advertiser, Offer, Payout, Currency
from tracker.models import APPROVED_STATUS, Click, Conversion
from user_profile.models import Profile, User


def make_advertiser_user(username):
    user = User.objects.create_user(username=username, password='pass')
    user.profile.role = Profile.Role.ADVERTISER
    user.profile.save()
    advertiser = Advertiser.objects.create(
        user=user,
        company=f'{username} Co',
        email=f'{username}@example.com',
    )
    return user, advertiser


def make_offer(advertiser, title='Test Offer', status='Active'):
    return Offer.objects.create(
        title=title,
        advertiser=advertiser,
        status=status,
        tracking_link='http://example.com/track',
        preview_link='http://example.com/preview',
    )


def make_payout(offer, payout=Decimal('10.00'), revenue=Decimal('12.00')):
    currency, _ = Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar'})
    return Payout.objects.create(
        offer=offer,
        payout=payout,
        revenue=revenue,
        goal_value='1',
        currency=currency,
    )


def make_click(offer, n=1):
    for _ in range(n):
        Click.objects.create(
            offer=offer,
            ip='1.2.3.4',
            revenue=Decimal('5.00'),
            payout=Decimal('3.00'),
        )


def make_conversion(offer, status=APPROVED_STATUS, payout=Decimal('10.00'), n=1, affiliate=None):
    for _ in range(n):
        Conversion.objects.create(
            offer=offer,
            affiliate=affiliate,
            status=status,
            payout=payout,
            revenue=payout,
        )

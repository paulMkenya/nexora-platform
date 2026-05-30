"""
Tests: auto-debit, double-charge prevention, negative-balance edge cases.
"""
import uuid
from decimal import Decimal
import pytest

from offer.models import Advertiser
from billing.models import AdvertiserWallet, WalletTransaction, TXN_DEBIT
from billing.tasks.debit import debit_conversion


def _make_advertiser(company='Acme'):
    from django.contrib.auth import get_user_model
    u = get_user_model().objects.create_user(
        username=f'adv_{uuid.uuid4().hex[:8]}', password='pw')
    return Advertiser.objects.create(company=company, email=f'{u.username}@example.com', user=u)


def _make_wallet(advertiser, balance='100.00', credit_limit='0.00', threshold='10.00'):
    return AdvertiserWallet.objects.create(
        advertiser=advertiser,
        balance=Decimal(balance),
        credit_limit=Decimal(credit_limit),
        low_balance_threshold=Decimal(threshold),
    )


def _make_offer(advertiser):
    from offer.models import Offer
    return Offer.objects.create(title='Test Offer', advertiser=advertiser)


def _make_click(offer, affiliate):
    from tracker.models import Click
    c = Click(
        offer=offer,
        affiliate=affiliate,
        affiliate_manager=None,
        ip='1.2.3.4',
        ua='test',
        country='US',
        revenue=Decimal('0.00'),
        payout=Decimal('0.00'),
    )
    c.save()
    return c


def _make_conversion(click, revenue='5.00', status='approved'):
    from tracker.models import Conversion
    c = Conversion(
        click_id=click.id,
        offer=click.offer,
        affiliate=click.affiliate,
        affiliate_manager=None,
        ip=click.ip,
        country=click.country,
        revenue=Decimal(revenue),
        payout=Decimal(revenue),
        goal_value='1',
        sum=float(revenue),
        status=status,
    )
    c.save()
    return c


@pytest.fixture
def affiliate(db):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user(username=f'aff_{uuid.uuid4().hex[:6]}', password='pw')


@pytest.mark.django_db
class TestDebitConversion:

    def test_normal_debit_reduces_balance(self, affiliate):
        adv = _make_advertiser()
        wallet = _make_wallet(adv, balance='100.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='5.00', status='approved')

        result = debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.balance == Decimal('95.00')
        assert 'Debited' in result

    def test_normal_debit_creates_transaction(self, affiliate):
        adv = _make_advertiser()
        _make_wallet(adv, balance='50.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='10.00', status='approved')

        debit_conversion(str(conv.id))

        txn = WalletTransaction.objects.get(reference=f'conversion:{conv.id}')
        assert txn.type == TXN_DEBIT
        assert txn.amount == Decimal('-10.00')
        assert txn.balance_after == Decimal('40.00')

    def test_double_debit_is_prevented(self, affiliate):
        adv = _make_advertiser()
        wallet = _make_wallet(adv, balance='100.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='20.00', status='approved')

        debit_conversion(str(conv.id))
        result2 = debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.balance == Decimal('80.00')
        assert 'Already debited' in result2
        assert WalletTransaction.objects.filter(
            reference=f'conversion:{conv.id}').count() == 1

    def test_debit_rejected_when_below_credit_limit(self, affiliate):
        adv = _make_advertiser()
        # balance=5, credit_limit=0 → can't debit 10
        wallet = _make_wallet(adv, balance='5.00', credit_limit='0.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='10.00', status='approved')

        result = debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.balance == Decimal('5.00')
        assert 'Insufficient balance' in result

    def test_debit_allowed_within_credit_limit(self, affiliate):
        adv = _make_advertiser()
        # balance=0, credit_limit=50 → debit of 30 is allowed (new balance=-30)
        wallet = _make_wallet(adv, balance='0.00', credit_limit='50.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='30.00', status='approved')

        result = debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.balance == Decimal('-30.00')
        assert 'Debited' in result

    def test_low_balance_alert_flag_set(self, affiliate):
        adv = _make_advertiser()
        wallet = _make_wallet(adv, balance='12.00', threshold='10.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='5.00', status='approved')  # balance → 7 < 10

        debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.low_balance_alert_sent is True

    def test_no_debit_for_non_approved(self, affiliate):
        adv = _make_advertiser()
        wallet = _make_wallet(adv, balance='100.00')
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='5.00', status='hold')

        result = debit_conversion(str(conv.id))

        wallet.refresh_from_db()
        assert wallet.balance == Decimal('100.00')
        assert 'not approved' in result

    def test_no_debit_when_no_wallet(self, affiliate):
        adv = _make_advertiser()  # no wallet created
        offer = _make_offer(adv)
        click = _make_click(offer, affiliate)
        conv = _make_conversion(click, revenue='5.00', status='approved')

        result = debit_conversion(str(conv.id))
        assert 'No wallet' in result

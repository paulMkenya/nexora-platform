"""Tests for affiliate payout views at /partner/payouts/."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from brands.models import Brand
from payouts.models import PayoutMethod, PayoutRequest, PayoutSettings, METHOD_PAYPAL
from user_profile.models import Profile

User = get_user_model()
CACHES_DUMMY = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}


def _approve(user):
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.save()


@override_settings(CACHES=CACHES_DUMMY)
class AffiliatePayoutsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='affpay', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def test_payouts_page_200(self):
        r = self.client.get('/partner/payouts/')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'payouts/affiliate_payouts.html')

    def test_payouts_page_anonymous_redirect(self):
        self.client.logout()
        r = self.client.get('/partner/payouts/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_add_paypal_method(self):
        r = self.client.post('/partner/payouts/methods/add/', {'method': 'paypal', 'email': 'me@pp.com'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(PayoutMethod.objects.filter(affiliate=self.user, method='paypal').exists())

    def test_add_crypto_method_rejected_while_dispatch_disabled(self):
        # CRYPTO_DISPATCH_ENABLED is off by default — the same kill-switch that
        # gates real fund movement also gates adding a crypto payout method at
        # all, so nobody can set one up expecting a payout that will silently
        # stall (see payouts/views/affiliate_views.py add_payout_method).
        addr = '0x' + 'a' * 40
        r = self.client.post('/partner/payouts/methods/add/', {
            'method': 'crypto', 'network': 'ETH', 'wallet_address': addr, 'asset': 'ETH',
        })
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PayoutMethod.objects.filter(affiliate=self.user, method='crypto').exists())

    @override_settings(CRYPTO_DISPATCH_ENABLED=True)
    def test_add_crypto_method_valid_evm(self):
        addr = '0x' + 'a' * 40
        r = self.client.post('/partner/payouts/methods/add/', {
            'method': 'crypto', 'network': 'ETH', 'wallet_address': addr, 'asset': 'ETH',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(PayoutMethod.objects.filter(affiliate=self.user, method='crypto').exists())

    @override_settings(CRYPTO_DISPATCH_ENABLED=True)
    def test_add_crypto_method_invalid_address_redirects_with_error(self):
        r = self.client.post('/partner/payouts/methods/add/', {
            'method': 'crypto', 'network': 'ETH', 'wallet_address': 'badaddr',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PayoutMethod.objects.filter(affiliate=self.user, method='crypto').exists())

    def test_delete_payout_method(self):
        pm = PayoutMethod.objects.create(affiliate=self.user, method='paypal', details={'email': 'x@y.com'})
        r = self.client.post(f'/partner/payouts/methods/{pm.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PayoutMethod.objects.filter(pk=pm.pk).exists())

    def test_delete_other_user_method_returns_404(self):
        other = User.objects.create_user(username='other_pay', password='pass')
        pm = PayoutMethod.objects.create(affiliate=other, method='paypal', details={'email': 'x@y.com'})
        r = self.client.post(f'/partner/payouts/methods/{pm.pk}/delete/')
        self.assertEqual(r.status_code, 404)

    def test_set_default_method(self):
        PayoutMethod.objects.create(
            affiliate=self.user, method='paypal', details={'email': 'a@a.com'}, is_default=True,
        )
        pm2 = PayoutMethod.objects.create(affiliate=self.user, method='wise', details={'email': 'b@b.com'})
        self.client.post(f'/partner/payouts/methods/{pm2.pk}/set-default/')
        pm2.refresh_from_db()
        self.assertTrue(pm2.is_default)

    def test_update_payout_settings(self):
        r = self.client.post('/partner/payouts/settings/', {'schedule': 'weekly'})
        self.assertEqual(r.status_code, 302)
        ps = PayoutSettings.objects.get(affiliate=self.user)
        self.assertEqual(ps.schedule, 'weekly')

    def test_validate_address_api_valid(self):
        addr = '0x' + 'a' * 40
        r = self.client.get('/partner/payouts/api/validate-address/', {'network': 'ETH', 'address': addr})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['valid'])

    def test_validate_address_api_invalid(self):
        r = self.client.get('/partner/payouts/api/validate-address/', {'network': 'ETH', 'address': 'bad'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['valid'])

    def test_request_early_payout_below_threshold(self):
        PayoutSettings.objects.create(affiliate=self.user, min_threshold=Decimal('500.00'))
        r = self.client.post('/partner/payouts/request/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PayoutRequest.objects.filter(affiliate=self.user).exists())

    def test_url_reversal(self):
        self.assertEqual(reverse('affiliate_ui:payouts'), '/partner/payouts/')


@override_settings(CACHES=CACHES_DUMMY)
class AdminPayoutViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(username='adminpay', password='pass', is_staff=True)
        self.client.force_login(self.staff)

    def test_payout_list_200(self):
        r = self.client.get('/admin/payouts/')
        self.assertEqual(r.status_code, 200)

    def test_payout_list_anonymous_redirect(self):
        self.client.logout()
        r = self.client.get('/admin/payouts/')
        self.assertIn(r.status_code, [302, 403])

    def test_bulk_approve(self):
        user = User.objects.create_user(username='aff_approve', password='pass')
        # Payout views are brand-scoped for non-superuser operators; the
        # affiliate must share the operator's (default) brand to be actionable.
        user.profile.brand = Brand.get_default()
        user.profile.save(update_fields=['brand'])
        req = PayoutRequest.objects.create(
            affiliate=user, amount=Decimal('100'), method=METHOD_PAYPAL, status='pending',
        )
        r = self.client.post('/admin/payouts/approve/', {'ids': [req.pk]})
        self.assertEqual(r.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_mark_paid(self):
        user = User.objects.create_user(username='aff_mark', password='pass')
        user.profile.brand = Brand.get_default()
        user.profile.save(update_fields=['brand'])
        req = PayoutRequest.objects.create(
            affiliate=user, amount=Decimal('100'), method=METHOD_PAYPAL, status='approved',
        )
        r = self.client.post('/admin/payouts/mark-paid/', {'ids': [req.pk], 'tx_ref': 'TXABC'})
        self.assertEqual(r.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'paid')
        self.assertEqual(req.tx_ref, 'TXABC')

    def test_csv_download(self):
        r = self.client.get('/admin/payouts/csv/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')

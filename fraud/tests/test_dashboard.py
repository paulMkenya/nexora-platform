"""Tests for the fraud dashboard view."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from offer.models import Offer
from tracker.models import Click

User = get_user_model()


class TestFraudDashboard(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff', password='pass', is_staff=True,
        )
        self.non_staff = User.objects.create_user(
            username='regular', password='pass', is_staff=False,
        )

    def _url(self):
        return reverse('fraud:dashboard')

    def test_redirects_unauthenticated(self):
        response = self.client.get(self._url())
        self.assertEqual(302, response.status_code)

    def test_redirects_non_staff(self):
        self.client.login(username='regular', password='pass')
        response = self.client.get(self._url())
        self.assertEqual(302, response.status_code)

    def test_renders_for_staff(self):
        self.client.login(username='staff', password='pass')
        response = self.client.get(self._url())
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Fraud Dashboard')

    def test_shows_flagged_clicks(self):
        offer = Offer.objects.create(title='Offer', tracking_link='http://x.com')
        Click.objects.create(
            ip='9.9.9.9', ua='bot', offer=offer, affiliate=self.non_staff,
            revenue=Decimal('0'), payout=Decimal('0'),
            fraud_score=80, fraud_reasons=['bot_ua:bot'], is_bot=True,
        )
        self.client.login(username='staff', password='pass')
        response = self.client.get(self._url())
        self.assertContains(response, '9.9.9.9')

    def test_whitelist_add_and_remove(self):
        self.client.login(username='staff', password='pass')
        add_url = reverse('fraud:whitelist-add')
        resp = self.client.post(add_url, {'entry_type': 'ip', 'value': '1.1.1.1', 'note': 'test'})
        self.assertEqual(302, resp.status_code)

        from fraud.models import FraudWhitelist
        wl = FraudWhitelist.objects.get(value='1.1.1.1')
        self.assertEqual(wl.entry_type, 'ip')

        remove_url = reverse('fraud:whitelist-remove', kwargs={'pk': wl.pk})
        resp = self.client.post(remove_url)
        self.assertEqual(302, resp.status_code)
        self.assertFalse(FraudWhitelist.objects.filter(value='1.1.1.1').exists())

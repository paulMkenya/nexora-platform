"""Tests for PENDING/unverified affiliate gating at view and endpoint level."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from brands.models import Brand
from offer.models import Offer, ACTIVE_STATUS
from user_profile.models import Profile

User = get_user_model()


def _make_brand():
    return Brand.objects.get_or_create(
        slug='gate-test',
        defaults=dict(
            name='GateBrand',
            primary_domain='gate.example.com',
            tracking_domain='t.gate.example.com',
            is_default=True,
        ),
    )[0]


def _make_affiliate(username, *, status=Profile.AffiliateStatus.PENDING, email_verified=False):
    brand = _make_brand()
    u = User.objects.create_user(username=username, password='pass')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.affiliate_status = status
    u.profile.email_verified = email_verified
    u.profile.brand = brand
    u.profile.save()
    return u


def _make_approved(username):
    return _make_affiliate(username, status=Profile.AffiliateStatus.APPROVED, email_verified=True)


class PendingAffiliateGatingTest(TestCase):
    """PENDING affiliates can reach dashboard but not offer/payout endpoints."""

    def setUp(self):
        self.pending = _make_affiliate('pending_aff')
        self.approved = _make_approved('approved_aff')
        # Branded to the same brand the affiliates belong to: offer visibility
        # is brand-only now, so an unbranded offer would 404 for everyone and
        # the gating assertion would pass for the wrong reason.
        self.offer = Offer.objects.create(
            title='Live Offer', status=ACTIVE_STATUS, brand=_make_brand())

    def test_pending_can_access_dashboard(self):
        self.client.force_login(self.pending)
        resp = self.client.get('/partner/dashboard/')
        self.assertEqual(resp.status_code, 200)

    def test_pending_dashboard_shows_banner(self):
        self.client.force_login(self.pending)
        resp = self.client.get('/partner/dashboard/')
        self.assertContains(resp, 'pending')

    def test_pending_blocked_from_offer_list(self):
        self.client.force_login(self.pending)
        resp = self.client.get('/partner/offers/')
        self.assertEqual(resp.status_code, 403)

    def test_pending_blocked_from_offer_detail(self):
        self.client.force_login(self.pending)
        url = reverse('affiliate_ui:offer_detail', args=[self.offer.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_pending_blocked_from_payouts(self):
        self.client.force_login(self.pending)
        resp = self.client.get('/partner/payouts/')
        self.assertEqual(resp.status_code, 403)

    def test_pending_blocked_from_payout_request(self):
        self.client.force_login(self.pending)
        resp = self.client.post('/partner/payouts/request/', {})
        self.assertEqual(resp.status_code, 403)

    def test_approved_can_access_offer_list(self):
        self.client.force_login(self.approved)
        resp = self.client.get('/partner/offers/')
        self.assertEqual(resp.status_code, 200)

    def test_approved_can_access_offer_detail(self):
        self.client.force_login(self.approved)
        url = reverse('affiliate_ui:offer_detail', args=[self.offer.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_approved_can_access_payouts(self):
        self.client.force_login(self.approved)
        resp = self.client.get('/partner/payouts/')
        self.assertEqual(resp.status_code, 200)

    def test_unverified_email_still_blocked_even_if_approved_status(self):
        """Verified email is required in addition to APPROVED status."""
        user = _make_affiliate('unverified_approved', status=Profile.AffiliateStatus.APPROVED, email_verified=False)
        self.client.force_login(user)
        resp = self.client.get('/partner/offers/')
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_offer_list_redirects_to_login(self):
        resp = self.client.get('/partner/offers/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/partner/login/', resp['Location'])

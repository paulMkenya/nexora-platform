"""Brand isolation for the operator payout views.

A brand operator must never see (or act on) another brand's payout requests;
a superuser sees all brands. Payout requests inherit their brand from the
affiliate's Profile.brand.
"""
from decimal import Decimal

from django.test import TestCase

from brands.models import Brand
from payouts.models import PayoutRequest, STATUS_PENDING, STATUS_APPROVED
from user_profile.models import Profile, User


class PayoutBrandScopeTestCase(TestCase):
    def setUp(self):
        self.brand_a = Brand.objects.create(
            slug='pa', name='Brand A', primary_domain='a.test', tracking_domain='t.a.test')
        self.brand_b = Brand.objects.create(
            slug='pb', name='Brand B', primary_domain='b.test', tracking_domain='t.b.test')

        self.aff_a = self._affiliate('aff_a', self.brand_a)
        self.aff_b = self._affiliate('aff_b', self.brand_b)

        self.req_a = PayoutRequest.objects.create(
            affiliate=self.aff_a, amount=Decimal('10.00'), status=STATUS_PENDING)
        self.req_b = PayoutRequest.objects.create(
            affiliate=self.aff_b, amount=Decimal('20.00'), status=STATUS_PENDING)

        # Brand A network admin (staff, not superuser).
        self.admin_a = User.objects.create_user('admin_a', password='pass', is_staff=True)
        pa = self.admin_a.profile
        pa.role = Profile.Role.NETWORK_ADMIN
        pa.brand = self.brand_a
        pa.save()

        self.superuser = User.objects.create_superuser('root', 'root@test.com', 'pass')

    def _affiliate(self, username, brand):
        u = User.objects.create_user(username, password='pass')
        p = u.profile
        p.role = Profile.Role.AFFILIATE
        p.brand = brand
        p.save()
        return u

    def test_brand_admin_sees_only_own_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/payouts/', HTTP_HOST='a.test')
        self.assertEqual(r.status_code, 200)
        ids = {pr.pk for pr in r.context['requests']}
        self.assertIn(self.req_a.pk, ids)
        self.assertNotIn(self.req_b.pk, ids)
        self.assertFalse(r.context['show_all_brands'])

    def test_superuser_sees_all_brands(self):
        self.client.force_login(self.superuser)
        r = self.client.get('/admin/payouts/', HTTP_HOST='a.test')
        self.assertEqual(r.status_code, 200)
        ids = {pr.pk for pr in r.context['requests']}
        self.assertIn(self.req_a.pk, ids)
        self.assertIn(self.req_b.pk, ids)
        self.assertTrue(r.context['show_all_brands'])

    def test_brand_admin_cannot_approve_other_brand(self):
        """A brand A admin POSTing brand B's id must not mutate it."""
        self.client.force_login(self.admin_a)
        r = self.client.post('/admin/payouts/approve/', {'ids': [self.req_b.pk]}, HTTP_HOST='a.test')
        self.assertEqual(r.status_code, 302)
        self.req_b.refresh_from_db()
        self.assertEqual(self.req_b.status, STATUS_PENDING)  # untouched

    def test_brand_admin_can_approve_own_brand(self):
        self.client.force_login(self.admin_a)
        self.client.post('/admin/payouts/approve/', {'ids': [self.req_a.pk]}, HTTP_HOST='a.test')
        self.req_a.refresh_from_db()
        self.assertEqual(self.req_a.status, STATUS_APPROVED)

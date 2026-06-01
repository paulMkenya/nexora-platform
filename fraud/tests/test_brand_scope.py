"""Brand isolation for the fraud dashboard.

Flagged clicks/conversions carry a brand; a brand operator must only see their
own brand's fraud signals, while a superuser sees every brand.
"""
from decimal import Decimal

from django.test import TestCase

from brands.models import Brand
from tracker.models import Click
from user_profile.models import Profile, User


class FraudBrandScopeTestCase(TestCase):
    def setUp(self):
        self.brand_a = Brand.objects.create(
            slug='fa', name='Brand A', primary_domain='a.test', tracking_domain='t.a.test')
        self.brand_b = Brand.objects.create(
            slug='fb', name='Brand B', primary_domain='b.test', tracking_domain='t.b.test')

        self._flagged_click(self.brand_a, '11.11.11.11')
        self._flagged_click(self.brand_b, '22.22.22.22')

        self.admin_a = User.objects.create_user('fadmin_a', password='pass', is_staff=True)
        p = self.admin_a.profile
        p.role = Profile.Role.NETWORK_ADMIN
        p.brand = self.brand_a
        p.save()

        self.superuser = User.objects.create_superuser('froot', 'froot@test.com', 'pass')

    def _flagged_click(self, brand, ip):
        return Click.objects.create(
            brand=brand, ip=ip, ua='bot', revenue=Decimal('0'), payout=Decimal('0'),
            fraud_score=90, fraud_reasons=['bot_ua:bot'], is_bot=True,
        )

    def test_brand_admin_sees_only_own_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/fraud/', HTTP_HOST='a.test')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '11.11.11.11')
        self.assertNotContains(r, '22.22.22.22')
        self.assertFalse(r.context['show_all_brands'])

    def test_superuser_sees_all_brands(self):
        self.client.force_login(self.superuser)
        r = self.client.get('/admin/fraud/', HTTP_HOST='a.test')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '11.11.11.11')
        self.assertContains(r, '22.22.22.22')
        self.assertTrue(r.context['show_all_brands'])

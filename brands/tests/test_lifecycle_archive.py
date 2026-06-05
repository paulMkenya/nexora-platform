"""Lifecycle (archive) write-side: archive / restore / guarded hard-delete and
the Archived home at /admin/archived/.

Covers the role hierarchy (platform owner vs brand admin vs affiliate manager),
object-level brand scoping, the financial-emptiness guard on hard delete, the
default-brand protection, and that read-side surfaces drop archived rows.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from offer.models import Advertiser, Offer
from payouts.models import METHOD_PAYPAL, STATUS_PENDING, PayoutRequest
from tracker.models import Conversion
from user_profile.models import Profile

User = get_user_model()


def _brand(slug, *, default=False):
    return Brand.objects.create(
        slug=slug, name=f'Brand {slug.upper()}',
        primary_domain=f'{slug}.test', tracking_domain=f't.{slug}.test',
        is_default=default,
    )


def _user(username, role, brand=None, *, is_staff=False):
    u = User.objects.create_user(username, password='pass', is_staff=is_staff)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


class LifecycleBase(TestCase):
    def setUp(self):
        self.brand_a = _brand('a', default=True)
        self.brand_b = _brand('b')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])

        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b, is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)

        self.aff_a = _user('aff_a', Profile.Role.AFFILIATE, self.brand_a)
        self.aff_b = _user('aff_b', Profile.Role.AFFILIATE, self.brand_b)

        self.adv_a = Advertiser.objects.create(company='Adv A', email='a@a.com', brand=self.brand_a)
        self.adv_b = Advertiser.objects.create(company='Adv B', email='b@b.com', brand=self.brand_b)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class ArchiveActionTest(LifecycleBase):
    def test_brand_admin_archives_own_affiliate(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/affiliate/{self.aff_a.profile.pk}/archive/')
        self.assertEqual(r.status_code, 302)
        self.aff_a.profile.refresh_from_db()
        self.assertTrue(self.aff_a.profile.is_archived)
        self.assertIsNotNone(self.aff_a.profile.archived_at)
        self.assertEqual(self.aff_a.profile.archived_by, self.admin_a)

    def test_archived_affiliate_drops_off_active_console(self):
        self.aff_a.profile.archive()
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/affiliates/')
        names = {p.user.username for p in r.context['profiles']}
        self.assertNotIn('aff_a', names)

    def test_brand_admin_cannot_archive_other_brand_affiliate(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/affiliate/{self.aff_b.profile.pk}/archive/')
        self.assertEqual(r.status_code, 404)
        self.aff_b.profile.refresh_from_db()
        self.assertFalse(self.aff_b.profile.is_archived)

    def test_brand_admin_archives_own_advertiser(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/advertiser/{self.adv_a.pk}/archive/')
        self.assertEqual(r.status_code, 302)
        self.adv_a.refresh_from_db()
        self.assertTrue(self.adv_a.is_archived)

    def test_brand_admin_cannot_archive_other_brand_advertiser(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/advertiser/{self.adv_b.pk}/archive/')
        self.assertEqual(r.status_code, 404)

    def test_restore_brings_affiliate_back(self):
        self.aff_a.profile.archive(by=self.admin_a)
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/affiliate/{self.aff_a.profile.pk}/restore/')
        self.assertEqual(r.status_code, 302)
        self.aff_a.profile.refresh_from_db()
        self.assertFalse(self.aff_a.profile.is_archived)
        self.assertIsNone(self.aff_a.profile.archived_at)

    def test_affiliate_manager_cannot_archive(self):
        self.client.force_login(self.mgr_a)
        r = self.client.post(f'/admin/archived/affiliate/{self.aff_a.profile.pk}/archive/')
        self.assertEqual(r.status_code, 403)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class ArchivedHomeTest(LifecycleBase):
    def setUp(self):
        super().setUp()
        self.aff_a.profile.archive()
        self.aff_b.profile.archive()
        self.adv_a.archive()

    def test_brand_admin_sees_only_own_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/archived/')
        self.assertEqual(r.status_code, 200)
        aff_names = {row['profile'].user.username for row in r.context['affiliates']}
        self.assertEqual(aff_names, {'aff_a'})
        adv_names = {row['advertiser'].company for row in r.context['advertisers']}
        self.assertEqual(adv_names, {'Adv A'})
        self.assertFalse(r.context['show_brands'])

    def test_owner_sees_all_brands_and_brand_section(self):
        self.brand_b.archive()
        self.client.force_login(self.owner)
        r = self.client.get('/admin/archived/')
        aff_names = {row['profile'].user.username for row in r.context['affiliates']}
        self.assertEqual(aff_names, {'aff_a', 'aff_b'})
        self.assertTrue(r.context['show_brands'])
        brand_names = {row['brand'].name for row in r.context['brands']}
        self.assertIn('Brand B', brand_names)

    def test_affiliate_manager_blocked(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/archived/').status_code, 403)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class AffiliateHardDeleteGuardTest(LifecycleBase):
    def test_affiliate_with_financials_cannot_be_deleted(self):
        PayoutRequest.objects.create(
            affiliate=self.aff_a, amount=Decimal('10.00'),
            method=METHOD_PAYPAL, status=STATUS_PENDING)
        self.aff_a.profile.archive()
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/affiliate/{self.aff_a.profile.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.aff_a.pk).exists())

    def test_empty_affiliate_is_deleted(self):
        self.aff_a.profile.archive()
        pk, profile_pk = self.aff_a.pk, self.aff_a.profile.pk
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/affiliate/{profile_pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=pk).exists())
        self.assertFalse(Profile.objects.filter(pk=profile_pk).exists())


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class AdvertiserHardDeleteGuardTest(LifecycleBase):
    def test_advertiser_with_conversions_cannot_be_deleted(self):
        offer = Offer.objects.create(title='O', description='d', advertiser=self.adv_a, brand=self.brand_a)
        Conversion.objects.create(offer=offer, brand=self.brand_a)
        self.adv_a.archive()
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/advertiser/{self.adv_a.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Advertiser.objects.filter(pk=self.adv_a.pk).exists())

    def test_empty_advertiser_deleted_and_offers_orphaned(self):
        offer = Offer.objects.create(title='O', description='d', advertiser=self.adv_a, brand=self.brand_a)
        self.adv_a.archive()
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/advertiser/{self.adv_a.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Advertiser.objects.filter(pk=self.adv_a.pk).exists())
        offer.refresh_from_db()
        self.assertIsNone(offer.advertiser_id)  # SET_NULL — offer retained


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class BrandLifecycleTest(LifecycleBase):
    def test_owner_archives_non_default_brand(self):
        self.client.force_login(self.owner)
        r = self.client.post(f'/admin/archived/brand/{self.brand_b.pk}/archive/')
        self.assertEqual(r.status_code, 302)
        self.brand_b.refresh_from_db()
        self.assertTrue(self.brand_b.is_archived)

    def test_default_brand_cannot_be_archived(self):
        self.client.force_login(self.owner)
        r = self.client.post(f'/admin/archived/brand/{self.brand_a.pk}/archive/')
        self.assertEqual(r.status_code, 302)
        self.brand_a.refresh_from_db()
        self.assertFalse(self.brand_a.is_archived)

    def test_brand_admin_cannot_archive_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/archived/brand/{self.brand_b.pk}/archive/')
        self.assertEqual(r.status_code, 403)

    def test_archived_brand_excluded_from_active_list_and_default(self):
        self.brand_b.archive()
        # get_default never returns an archived brand
        self.assertNotEqual(Brand.get_default().pk, self.brand_b.pk)
        self.client.force_login(self.owner)
        r = self.client.get('/admin/brands/')
        listed = {b.pk for b in r.context['brands']}
        self.assertNotIn(self.brand_b.pk, listed)

    def test_brand_with_financials_blocked_from_hard_delete(self):
        Conversion.objects.create(brand=self.brand_b)
        self.brand_b.archive()
        self.client.force_login(self.owner)
        r = self.client.post(f'/admin/brands/{self.brand_b.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Brand.objects.filter(pk=self.brand_b.pk).exists())

    def test_empty_archived_brand_hard_deleted(self):
        self.brand_b.archive()
        self.client.force_login(self.owner)
        r = self.client.post(f'/admin/brands/{self.brand_b.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Brand.objects.filter(pk=self.brand_b.pk).exists())

    def test_default_brand_hard_delete_still_protected(self):
        self.client.force_login(self.owner)
        r = self.client.post(f'/admin/brands/{self.brand_a.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Brand.objects.filter(pk=self.brand_a.pk).exists())

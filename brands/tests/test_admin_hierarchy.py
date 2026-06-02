"""Per-brand admin hierarchy: scoping, moderation, role appointment, model-admin lockout.

Roles under test:
  * PLATFORM OWNER  = superuser (sees all brands, full Django admin).
  * BRAND ADMIN     = NETWORK_ADMIN + Profile.brand, is_staff, not superuser.
  * AFFILIATE MGR   = AFFILIATE_MANAGER + Profile.brand; only assigned affiliates.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=f'Brand {slug.upper()}',
        primary_domain=f'{slug}.test', tracking_domain=f't.{slug}.test',
        is_default=(slug == 'a'),
    )


def _user(username, role, brand=None, *, is_staff=False, is_superuser=False, manager=None):
    u = User.objects.create_user(username, password='pass',
                                 is_staff=is_staff, is_superuser=is_superuser)
    p = u.profile
    p.role = role
    p.brand = brand
    if manager is not None:
        p.manager = manager
    p.save()
    return u


class AdminHierarchyBase(TestCase):
    def setUp(self):
        self.brand_a = _brand('a')
        self.brand_b = _brand('b')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        # The platform owner is not an affiliate; give them a non-affiliate role
        # so they don't show up in affiliate listings.
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])
        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b, is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)
        self.mgr_b = _user('mgr_b', Profile.Role.AFFILIATE_MANAGER, self.brand_b)

        # Affiliates: one assigned to mgr_a, one unassigned (brand A), one brand B.
        self.aff_a_assigned = _user('aff_a1', Profile.Role.AFFILIATE, self.brand_a, manager=self.mgr_a)
        self.aff_a_unassigned = _user('aff_a2', Profile.Role.AFFILIATE, self.brand_a)
        self.aff_b = _user('aff_b1', Profile.Role.AFFILIATE, self.brand_b)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class BrandAdminScopeTest(AdminHierarchyBase):
    def test_brand_admin_sees_only_own_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/affiliates/')
        self.assertEqual(r.status_code, 200)
        names = {p.user.username for p in r.context['profiles']}
        self.assertEqual(names, {'aff_a1', 'aff_a2'})
        self.assertTrue(r.context['can_moderate'])

    def test_brand_admin_cannot_view_other_brand_affiliate_by_id(self):
        self.client.force_login(self.admin_a)
        r = self.client.get(f'/admin/affiliates/{self.aff_b.profile.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_brand_admin_cannot_approve_other_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/affiliates/{self.aff_b.profile.pk}/approve/')
        self.assertEqual(r.status_code, 404)
        self.aff_b.profile.refresh_from_db()
        self.assertEqual(self.aff_b.profile.affiliate_status, Profile.AffiliateStatus.PENDING)

    def test_brand_admin_can_approve_own_brand(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(f'/admin/affiliates/{self.aff_a_unassigned.profile.pk}/approve/')
        self.assertEqual(r.status_code, 302)
        self.aff_a_unassigned.profile.refresh_from_db()
        self.assertEqual(self.aff_a_unassigned.profile.affiliate_status, Profile.AffiliateStatus.APPROVED)

    def test_brand_admin_blocked_from_django_model_admin(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/')
        self.assertRedirects(r, '/admin/dashboard/', fetch_redirect_response=False)

    def test_brand_admin_cannot_manage_brands(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get('/admin/brands/').status_code, 403)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class AffiliateManagerScopeTest(AdminHierarchyBase):
    def test_manager_sees_only_assigned_affiliates(self):
        self.client.force_login(self.mgr_a)
        r = self.client.get('/admin/affiliates/')
        self.assertEqual(r.status_code, 200)
        names = {p.user.username for p in r.context['profiles']}
        self.assertEqual(names, {'aff_a1'})
        self.assertFalse(r.context['can_moderate'])
        self.assertTrue(r.context['is_manager_view'])

    def test_manager_can_view_assigned_detail(self):
        self.client.force_login(self.mgr_a)
        r = self.client.get(f'/admin/affiliates/{self.aff_a_assigned.profile.pk}/')
        self.assertEqual(r.status_code, 200)

    def test_manager_cannot_view_unassigned_by_id(self):
        self.client.force_login(self.mgr_a)
        r = self.client.get(f'/admin/affiliates/{self.aff_a_unassigned.profile.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_manager_cannot_view_other_brand_by_id(self):
        self.client.force_login(self.mgr_a)
        r = self.client.get(f'/admin/affiliates/{self.aff_b.profile.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_manager_cannot_approve(self):
        self.client.force_login(self.mgr_a)
        r = self.client.post(f'/admin/affiliates/{self.aff_a_assigned.profile.pk}/approve/')
        self.assertEqual(r.status_code, 403)
        self.aff_a_assigned.profile.refresh_from_db()
        self.assertEqual(self.aff_a_assigned.profile.affiliate_status, Profile.AffiliateStatus.PENDING)

    def test_manager_cannot_suspend(self):
        self.client.force_login(self.mgr_a)
        r = self.client.post(f'/admin/affiliates/{self.aff_a_assigned.profile.pk}/suspend/')
        self.assertEqual(r.status_code, 403)

    def test_manager_cannot_assign_manager(self):
        self.client.force_login(self.mgr_a)
        r = self.client.post(
            f'/admin/affiliates/{self.aff_a_assigned.profile.pk}/assign-manager/',
            {'manager': self.mgr_a.pk},
        )
        self.assertEqual(r.status_code, 403)

    def test_manager_blocked_from_django_model_admin(self):
        self.client.force_login(self.mgr_a)
        r = self.client.get('/admin/')
        self.assertRedirects(r, '/admin/affiliates/', fetch_redirect_response=False)


class ManagerAssignmentTest(AdminHierarchyBase):
    def test_brand_admin_assigns_manager(self):
        self.client.force_login(self.admin_a)
        r = self.client.post(
            f'/admin/affiliates/{self.aff_a_unassigned.profile.pk}/assign-manager/',
            {'manager': self.mgr_a.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.aff_a_unassigned.profile.refresh_from_db()
        self.assertEqual(self.aff_a_unassigned.profile.manager, self.mgr_a)

    def test_unassign_manager(self):
        self.client.force_login(self.admin_a)
        self.client.post(
            f'/admin/affiliates/{self.aff_a_assigned.profile.pk}/assign-manager/',
            {'manager': ''},
        )
        self.aff_a_assigned.profile.refresh_from_db()
        self.assertIsNone(self.aff_a_assigned.profile.manager)

    def test_cannot_assign_other_brand_manager(self):
        """A brand-B manager is not a valid manager for a brand-A affiliate."""
        self.client.force_login(self.admin_a)
        self.client.post(
            f'/admin/affiliates/{self.aff_a_unassigned.profile.pk}/assign-manager/',
            {'manager': self.mgr_b.pk},
        )
        self.aff_a_unassigned.profile.refresh_from_db()
        self.assertIsNone(self.aff_a_unassigned.profile.manager)


class RoleAppointmentTest(AdminHierarchyBase):
    def test_owner_appoints_brand_admin(self):
        target = _user('newadmin', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.owner)
        r = self.client.post('/admin/roles/appoint-brand-admin/',
                             {'identifier': 'newadmin', 'brand': self.brand_b.pk})
        self.assertEqual(r.status_code, 302)
        target.refresh_from_db()
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.role, Profile.Role.NETWORK_ADMIN)
        self.assertEqual(target.profile.brand, self.brand_b)
        self.assertTrue(target.is_staff)
        self.assertFalse(target.is_superuser)

    def test_brand_admin_appoints_manager_in_own_brand(self):
        target = _user('newmgr', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        r = self.client.post('/admin/roles/appoint-manager/', {'identifier': 'newmgr'})
        self.assertEqual(r.status_code, 302)
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.role, Profile.Role.AFFILIATE_MANAGER)
        self.assertEqual(target.profile.brand, self.brand_a)

    def test_brand_admin_manager_appointment_forced_to_own_brand(self):
        """Even if a brand admin posts another brand id, the manager lands in their brand."""
        target = _user('newmgr2', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        self.client.post('/admin/roles/appoint-manager/',
                         {'identifier': 'newmgr2', 'brand': self.brand_b.pk})
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.brand, self.brand_a)

    def test_brand_admin_cannot_appoint_brand_admin(self):
        target = _user('wannabe', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        r = self.client.post('/admin/roles/appoint-brand-admin/',
                             {'identifier': 'wannabe', 'brand': self.brand_a.pk})
        self.assertEqual(r.status_code, 403)
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.role, Profile.Role.AFFILIATE)

    def test_appointed_manager_is_never_superuser(self):
        target = _user('mgr_target', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        self.client.post('/admin/roles/appoint-manager/', {'identifier': 'mgr_target'})
        target.refresh_from_db()
        self.assertFalse(target.is_superuser)
        self.assertFalse(target.is_staff)

    def test_manager_cannot_open_roles_console(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/roles/').status_code, 403)


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class PlatformOwnerTest(AdminHierarchyBase):
    def test_owner_sees_all_brands_affiliates(self):
        self.client.force_login(self.owner)
        r = self.client.get('/admin/affiliates/')
        names = {p.user.username for p in r.context['profiles']}
        self.assertEqual(names, {'aff_a1', 'aff_a2', 'aff_b1'})

    def test_owner_can_open_django_model_admin(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_owner_can_manage_brands(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/brands/').status_code, 200)

    def test_owner_can_open_roles_console(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/roles/').status_code, 200)

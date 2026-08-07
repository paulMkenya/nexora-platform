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

    # 2026-08-07: a brand admin is now full admin OF ITS OWN BRAND, so the
    # brands page is reachable — but it is scoped to that one brand and the
    # cross-tenant actions behind it stay platform-owner-only. Was: a flat 403.
    def test_brand_admin_sees_only_its_own_brand_on_brands_page(self):
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/brands/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([b.pk for b in r.context['brands']], [self.brand_a.pk])
        self.assertNotContains(r, self.brand_b.name)

    def test_brand_admin_cannot_create_or_delete_a_brand(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get('/admin/brands/new/').status_code, 403)
        self.assertEqual(
            self.client.post(f'/admin/brands/{self.brand_a.pk}/delete/').status_code, 403)

    def test_brand_admin_cannot_edit_another_brand(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(
            self.client.get(f'/admin/brands/{self.brand_b.pk}/edit/').status_code, 403)

    def test_brand_admin_cannot_change_its_own_domains_or_default_flag(self):
        """The platform-level fields are ignored for a non-owner even when
        POSTed directly — the template hiding them is not the control.

        Run as admin_b: brand_b is NOT the default, so a successful grab of
        is_default would be visible. (brand_a already is the default, which
        would make that assertion pass for the wrong reason.)"""
        self.assertFalse(self.brand_b.is_default)
        self.client.force_login(self.admin_b)
        original_domain = self.brand_b.primary_domain
        original_tracking = self.brand_b.tracking_domain
        r = self.client.post(f'/admin/brands/{self.brand_b.pk}/edit/', {
            'name': 'Renamed B',
            'primary_domain': 'stolen.example.com',
            'tracking_domain': 'stolen-t.example.com',
            'is_default': 'on',
        })
        self.assertEqual(r.status_code, 302)
        self.brand_b.refresh_from_db()
        self.assertEqual(self.brand_b.name, 'Renamed B')                    # allowed
        self.assertEqual(self.brand_b.primary_domain, original_domain)      # ignored
        self.assertEqual(self.brand_b.tracking_domain, original_tracking)   # ignored
        self.assertFalse(self.brand_b.is_default)                           # ignored


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

    # 2026-08-07: a brand admin may now appoint co-admins, but only inside its
    # own brand — the brand comes from the actor, never the form. Was: 403.
    def test_brand_admin_can_appoint_co_admin_in_own_brand(self):
        target = _user('wannabe', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        r = self.client.post('/admin/roles/appoint-brand-admin/',
                             {'identifier': 'wannabe'})
        self.assertEqual(r.status_code, 302)
        target.profile.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(target.profile.role, Profile.Role.NETWORK_ADMIN)
        self.assertEqual(target.profile.brand, self.brand_a)
        self.assertTrue(target.is_staff)
        self.assertFalse(target.is_superuser)

    def test_brand_admin_appointing_ignores_a_posted_foreign_brand(self):
        target = _user('wannabe2', Profile.Role.AFFILIATE, self.brand_a)
        self.client.force_login(self.admin_a)
        self.client.post('/admin/roles/appoint-brand-admin/',
                         {'identifier': 'wannabe2', 'brand': self.brand_b.pk})
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.brand, self.brand_a)

    def test_brand_admin_cannot_demote_a_platform_owner(self):
        owner = _user('someowner', Profile.Role.NETWORK_ADMIN, self.brand_a)
        owner.is_superuser = True
        owner.is_staff = True
        owner.save()
        self.client.force_login(self.admin_a)
        self.client.post('/admin/roles/appoint-brand-admin/', {'identifier': 'someowner'})
        owner.refresh_from_db()
        self.assertTrue(owner.is_superuser)

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

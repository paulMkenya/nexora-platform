"""Convert a WON PlatformLead into a Brand (owner-only).

Covers the spec:
  * convert a WON lead creates a brand pre-filled from the lead and links it
    (lead.converted_brand + converted_at set, sales_stage forced WON)
  * the Convert action appears ONLY on WON, unconverted leads
  * converting twice is blocked server-side (not just UI)
  * a duplicate slug / primary_domain / tracking_domain is rejected with a
    message and creates nothing
  * non-owner (brand admin / anon) cannot convert (403 / login redirect)
  * a non-WON lead exposes no convert action
  * the existing plain brand-creation flow still works unchanged
  * a lead email matching an existing user is handled gracefully (no crash)
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from platform_leads.models import PlatformLead
from user_profile.models import Profile

User = get_user_model()
HOST = 'cpa.test'


class ConvertBase(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(
            slug='default', name='DefaultBrand', primary_domain=HOST,
            tracking_domain=f't.{HOST}', is_default=True)

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.brand_admin = User.objects.create_user(
            'badmin', email='badmin@test.com', password='pass', is_staff=True)
        self.brand_admin.profile.role = Profile.Role.NETWORK_ADMIN
        self.brand_admin.profile.brand = self.brand
        self.brand_admin.profile.save()

        self.won = PlatformLead.objects.create(
            lead_type='NETWORK', name='Pat Prospect', email='pat@won.test',
            company='WonCo', sales_stage=PlatformLead.Stage.WON)
        self.new_lead = PlatformLead.objects.create(
            lead_type='SOLO', name='Sam New', email='sam@new.test',
            sales_stage=PlatformLead.Stage.NEW)

    def _convert_post(self, lead, **overrides):
        data = {
            'from_lead': str(lead.id),
            'slug': 'wonco', 'name': 'WonCo',
            'primary_domain': 'app.wonco.test',
            'tracking_domain': 't.wonco.test',
        }
        data.update(overrides)
        return self.client.post('/admin/brands/new/', data, HTTP_HOST=HOST)


class ConvertFlowTest(ConvertBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_get_prefills_form_from_won_lead(self):
        resp = self.client.get(f'/admin/brands/new/?from_lead={self.won.id}', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Converting sales lead')
        self.assertContains(resp, 'value="WonCo"')          # name <- company
        self.assertContains(resp, 'value="pat@won.test"')   # support_email <- email
        self.assertContains(resp, 'name="from_lead"')

    def test_convert_creates_and_links_brand(self):
        resp = self._convert_post(self.won)
        self.assertEqual(resp.status_code, 302)
        brand = Brand.objects.get(slug='wonco')
        self.assertIn(f'/admin/brands/{brand.pk}/setup/', resp.url)
        self.won.refresh_from_db()
        self.assertEqual(self.won.converted_brand_id, brand.pk)
        self.assertIsNotNone(self.won.converted_at)
        self.assertEqual(self.won.sales_stage, PlatformLead.Stage.WON)
        # notification_email mapped from the lead.
        self.assertEqual(brand.notification_email, 'pat@won.test')

    def test_convert_forces_won_stage(self):
        # Even a non-WON lead reached directly is forced to WON on conversion.
        resp = self._convert_post(self.new_lead, slug='newco', name='NewCo',
                                  primary_domain='app.newco.test',
                                  tracking_domain='t.newco.test')
        self.assertEqual(resp.status_code, 302)
        self.new_lead.refresh_from_db()
        self.assertEqual(self.new_lead.sales_stage, PlatformLead.Stage.WON)
        self.assertIsNotNone(self.new_lead.converted_brand_id)

    def test_double_convert_blocked_server_side(self):
        self._convert_post(self.won)
        self.won.refresh_from_db()
        first_brand_id = self.won.converted_brand_id
        before = Brand.objects.count()
        # Second attempt with DIFFERENT domains must NOT create another brand.
        resp = self._convert_post(self.won, slug='wonco2', name='WonCo2',
                                  primary_domain='app.wonco2.test',
                                  tracking_domain='t.wonco2.test')
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/admin/brands/{first_brand_id}/setup/', resp.url)
        self.assertEqual(Brand.objects.count(), before)
        self.assertFalse(Brand.objects.filter(slug='wonco2').exists())
        self.won.refresh_from_db()
        self.assertEqual(self.won.converted_brand_id, first_brand_id)  # unchanged

    def test_already_converted_get_redirects_to_brand(self):
        self._convert_post(self.won)
        self.won.refresh_from_db()
        resp = self.client.get(f'/admin/brands/new/?from_lead={self.won.id}', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/admin/brands/{self.won.converted_brand_id}/setup/', resp.url)

    def test_duplicate_primary_domain_rejected(self):
        Brand.objects.create(slug='taken', name='Taken',
                             primary_domain='app.wonco.test', tracking_domain='t.taken.test')
        before = Brand.objects.count()
        resp = self._convert_post(self.won)  # primary_domain collides
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already registered')
        self.assertEqual(Brand.objects.count(), before)
        self.won.refresh_from_db()
        self.assertIsNone(self.won.converted_brand_id)  # not linked

    def test_duplicate_slug_rejected(self):
        Brand.objects.create(slug='wonco', name='Existing',
                             primary_domain='app.existing.test', tracking_domain='t.existing.test')
        before = Brand.objects.count()
        resp = self._convert_post(self.won)  # slug collides
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already taken')
        self.assertEqual(Brand.objects.count(), before)
        self.won.refresh_from_db()
        self.assertIsNone(self.won.converted_brand_id)

    def test_email_matches_existing_user_handled(self):
        User.objects.create_user('dup', email='pat@won.test', password='pass')
        resp = self._convert_post(self.won)
        self.assertEqual(resp.status_code, 302)  # still succeeds, no crash
        self.won.refresh_from_db()
        self.assertIsNotNone(self.won.converted_brand_id)

    def test_plain_brand_create_still_works(self):
        # No from_lead -> ordinary creation, unchanged.
        resp = self.client.post('/admin/brands/new/', {
            'slug': 'plain', 'name': 'Plain',
            'primary_domain': 'app.plain.test', 'tracking_domain': 't.plain.test',
        }, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Brand.objects.filter(slug='plain').exists())

    # ── UI visibility ────────────────────────────────────────────────────────
    def test_pipeline_shows_convert_for_won_unconverted(self):
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST=HOST)
        self.assertContains(resp, 'Convert to brand')

    def test_pipeline_shows_link_after_conversion(self):
        self._convert_post(self.won)
        # Lost the only WON-unconverted lead; NEW lead never offers convert.
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST=HOST)
        self.assertContains(resp, 'Converted')
        self.assertNotContains(resp, 'Convert to brand')

    def test_detail_won_shows_convert_then_link(self):
        resp = self.client.get(f'/admin/platform-leads/{self.won.id}/', HTTP_HOST=HOST)
        self.assertContains(resp, 'Convert to brand')
        self._convert_post(self.won)
        resp = self.client.get(f'/admin/platform-leads/{self.won.id}/', HTTP_HOST=HOST)
        self.assertContains(resp, 'Converted')
        self.assertNotContains(resp, 'Convert to brand')

    def test_non_won_lead_has_no_convert_action(self):
        resp = self.client.get(f'/admin/platform-leads/{self.new_lead.id}/', HTTP_HOST=HOST)
        self.assertNotContains(resp, 'Convert to brand')


class ConvertAuthTest(ConvertBase):
    def test_brand_admin_cannot_get_convert_form(self):
        self.client.force_login(self.brand_admin)
        resp = self.client.get(f'/admin/brands/new/?from_lead={self.won.id}', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 403)

    def test_brand_admin_cannot_convert_post(self):
        self.client.force_login(self.brand_admin)
        before = Brand.objects.count()
        resp = self._convert_post(self.won)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Brand.objects.count(), before)
        self.won.refresh_from_db()
        self.assertIsNone(self.won.converted_brand_id)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(f'/admin/brands/new/?from_lead={self.won.id}', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('/setup/', resp.url)

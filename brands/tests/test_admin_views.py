"""HTTP-level tests for the network-admin brand views at /admin/brands/.

Regression coverage for the add/edit 500 (brand_form.html prefills inputs from
``post.<field>``; GET renders must always supply ``post``).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand

User = get_user_model()
HOST = 'admin.example.com'


def _make_default_brand():
    return Brand.objects.create(
        slug='default', name='DefaultBrand',
        primary_domain=HOST, tracking_domain=f't.{HOST}',
        is_default=True,
    )


class BrandAdminViewTest(TestCase):
    def setUp(self):
        self.brand = _make_default_brand()
        self.admin = User.objects.create_user(
            username='brandadmin', password='pass', is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_add_brand_get_renders_form(self):
        resp = self.client.get('/admin/brands/new/', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Create Brand')

    def test_edit_brand_get_renders_form(self):
        resp = self.client.get(f'/admin/brands/{self.brand.pk}/edit/', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Edit Brand')
        self.assertContains(resp, 'DefaultBrand')

    def test_add_brand_post_creates_brand(self):
        resp = self.client.post('/admin/brands/new/', {
            'slug': 'acme', 'name': 'Acme',
            'primary_domain': 'acme.example.com',
            'tracking_domain': 't.acme.example.com',
        }, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Brand.objects.filter(slug='acme', name='Acme').exists())

    def test_add_brand_invalid_rerenders_with_error(self):
        # Missing required fields -> 200 re-render with errors (post path).
        resp = self.client.post('/admin/brands/new/', {'name': 'NoSlug'}, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Slug is required.')
        # Submitted value preserved via post.*
        self.assertContains(resp, 'NoSlug')

    def test_edit_brand_post_saves(self):
        resp = self.client.post(f'/admin/brands/{self.brand.pk}/edit/', {
            'name': 'Renamed',
            'primary_domain': HOST,
            'tracking_domain': f't.{HOST}',
        }, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.name, 'Renamed')

    def test_default_brand_delete_protected(self):
        resp = self.client.post(f'/admin/brands/{self.brand.pk}/delete/', HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())

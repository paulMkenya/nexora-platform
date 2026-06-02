"""Brand-aware self-service password reset."""
import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from brands.models import Brand

User = get_user_model()


class PasswordResetTest(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(
            slug='pr', name='ResetBrand',
            primary_domain='pr.test', tracking_domain='t.pr.test',
            is_default=True, support_email='help@pr.test',
        )
        self.user = User.objects.create_user(
            'reset_user', email='user@pr.test', password='oldpass123')

    def test_login_page_has_forgot_link(self):
        r = self.client.get('/partner/login/', HTTP_HOST='pr.test')
        self.assertContains(r, '/partner/password-reset/')

    def test_reset_sends_brand_aware_email(self):
        r = self.client.post('/partner/password-reset/', {'email': 'user@pr.test'}, HTTP_HOST='pr.test')
        self.assertRedirects(r, '/partner/password-reset/done/', fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('user@pr.test', msg.to)
        self.assertIn('ResetBrand', msg.subject)        # brand name in subject
        self.assertIn('ResetBrand', msg.body)           # brand name in body
        self.assertIn('help@pr.test', msg.body)         # brand support email
        self.assertIn('pr.test/partner/reset/', msg.body)  # link on the brand host

    def test_unknown_email_no_leak_no_mail(self):
        r = self.client.post('/partner/password-reset/', {'email': 'nobody@pr.test'}, HTTP_HOST='pr.test')
        self.assertRedirects(r, '/partner/password-reset/done/', fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow_changes_password(self):
        self.client.post('/partner/password-reset/', {'email': 'user@pr.test'}, HTTP_HOST='pr.test')
        body = mail.outbox[0].body
        m = re.search(r'/partner/reset/[^/\s]+/[^/\s]+/', body)
        self.assertIsNotNone(m)
        # GET the link → confirm view moves the token into the session and redirects.
        r = self.client.get(m.group(0), HTTP_HOST='pr.test')
        self.assertEqual(r.status_code, 302)
        r2 = self.client.post(
            r.url, {'new_password1': 'BrandNewPass99', 'new_password2': 'BrandNewPass99'},
            HTTP_HOST='pr.test')
        self.assertRedirects(r2, '/partner/reset/done/', fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPass99'))

    def test_brand_b_link_uses_brand_b_host(self):
        Brand.objects.create(
            slug='prb', name='OtherBrand',
            primary_domain='prb.test', tracking_domain='t.prb.test', is_default=False)
        self.client.post('/partner/password-reset/', {'email': 'user@pr.test'}, HTTP_HOST='prb.test')
        body = mail.outbox[0].body
        self.assertIn('OtherBrand', body)
        self.assertIn('prb.test/partner/reset/', body)

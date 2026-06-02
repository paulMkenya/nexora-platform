"""Per-brand SMTP config: encryption, connection selection, settings UI, and
brand-aware password-reset delivery."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from brands.email import connection_for_brand, from_email_for_brand
from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()


def _user(username, role, brand=None, is_staff=False, is_superuser=False):
    u = User.objects.create_user(username, password='pass', is_staff=is_staff, is_superuser=is_superuser)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


class SmtpPasswordEncryptionTest(TestCase):
    def test_password_round_trips_and_is_not_plaintext(self):
        b = Brand.objects.create(slug='enc', name='Enc', primary_domain='enc.test', tracking_domain='t.enc.test')
        b.set_smtp_password('s3cret-pw')
        b.save()
        b.refresh_from_db()
        self.assertEqual(b.get_smtp_password(), 's3cret-pw')
        self.assertNotIn('s3cret-pw', b.smtp_password_encrypted)  # stored encrypted
        self.assertTrue(b.smtp_password_encrypted)

    def test_clear_password(self):
        b = Brand.objects.create(slug='enc2', name='Enc2', primary_domain='e2.test', tracking_domain='t.e2.test')
        b.set_smtp_password('x')
        b.set_smtp_password('')
        self.assertEqual(b.smtp_password_encrypted, '')
        self.assertEqual(b.get_smtp_password(), '')


class ConnectionSelectionTest(TestCase):
    def test_configured_brand_uses_its_own_smtp(self):
        b = Brand.objects.create(
            slug='cfg', name='Cfg', primary_domain='cfg.test', tracking_domain='t.cfg.test',
            smtp_host='smtp.cfg.test', smtp_from_email='no-reply@cfg.test')
        conn = connection_for_brand(b)
        self.assertEqual(conn.host, 'smtp.cfg.test')
        self.assertEqual(from_email_for_brand(b), 'no-reply@cfg.test')

    def test_unconfigured_brand_falls_back(self):
        b = Brand.objects.create(slug='nocfg', name='NoCfg', primary_domain='nc.test', tracking_domain='t.nc.test')
        # No smtp_host/from → not configured → default From, default backend.
        self.assertFalse(b.smtp_configured)
        self.assertEqual(from_email_for_brand(b), 'no-reply@cloudtrade.pro')


class EmailSettingsUITest(TestCase):
    def setUp(self):
        self.brand_a = Brand.objects.create(
            slug='ea', name='BrandA', primary_domain='ea.test', tracking_domain='t.ea.test', is_default=True)
        self.brand_b = Brand.objects.create(
            slug='eb', name='BrandB', primary_domain='eb.test', tracking_domain='t.eb.test')
        self.admin_a = _user('ea_admin', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.mgr_a = _user('ea_mgr', Profile.Role.AFFILIATE_MANAGER, self.brand_a)
        self.owner = User.objects.create_superuser('ea_owner', 'o@ea.test', 'pass')

    def test_brand_admin_saves_own_smtp(self):
        self.client.force_login(self.admin_a)
        r = self.client.post('/admin/brands/email-settings/', {
            'smtp_from_email': 'no-reply@ea.test', 'smtp_host': 'smtp.ea.test',
            'smtp_port': '587', 'smtp_username': 'u', 'smtp_password': 'pw', 'smtp_use_tls': 'on',
        })
        self.assertEqual(r.status_code, 302)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.smtp_host, 'smtp.ea.test')
        self.assertEqual(self.brand_a.get_smtp_password(), 'pw')
        self.assertTrue(self.brand_a.smtp_configured)
        # The other brand is untouched.
        self.brand_b.refresh_from_db()
        self.assertFalse(self.brand_b.smtp_configured)

    def test_blank_password_keeps_existing(self):
        self.brand_a.set_smtp_password('keepme')
        self.brand_a.smtp_host = 'h'
        self.brand_a.smtp_from_email = 'f@ea.test'
        self.brand_a.save()
        self.client.force_login(self.admin_a)
        self.client.post('/admin/brands/email-settings/', {
            'smtp_from_email': 'f@ea.test', 'smtp_host': 'h', 'smtp_port': '587', 'smtp_password': '',
        })
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.get_smtp_password(), 'keepme')

    def test_manager_cannot_access(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/brands/email-settings/').status_code, 403)

    def test_owner_can_access(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/brands/email-settings/').status_code, 200)

    def test_password_never_rendered(self):
        self.brand_a.set_smtp_password('topsecret')
        self.brand_a.smtp_host = 'h'
        self.brand_a.smtp_from_email = 'f@ea.test'
        self.brand_a.save()
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/brands/email-settings/')
        self.assertNotContains(r, 'topsecret')
        self.assertNotContains(r, self.brand_a.smtp_password_encrypted)


class BrandAwareResetDeliveryTest(TestCase):
    def test_reset_uses_brand_from_address(self):
        Brand.objects.create(
            slug='rb', name='ResetCo', primary_domain='rb.test', tracking_domain='t.rb.test',
            is_default=True, smtp_from_email='no-reply@rb.test')
        User.objects.create_user('ru', email='ru@rb.test', password='oldpass123')
        self.client.post('/partner/password-reset/', {'email': 'ru@rb.test'}, HTTP_HOST='rb.test')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, 'no-reply@rb.test')

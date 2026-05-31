"""Tests for affiliate self-registration and email verification."""
from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.test import TestCase, override_settings

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()

_REG_URL = '/partner/register/'
_EMAIL_SALT = 'affiliate-email-verify'


def _make_brand():
    return Brand.objects.create(
        slug='test-reg',
        name='TestBrand',
        primary_domain='testbrand.example.com',
        tracking_domain='t.testbrand.example.com',
        is_default=True,
    )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RegistrationTest(TestCase):
    def setUp(self):
        self.brand = _make_brand()

    def _post(self, overrides=None):
        data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane@example.com',
            'password1': 'Str0ngP@ssword!',
            'password2': 'Str0ngP@ssword!',
        }
        if overrides:
            data.update(overrides)
        return self.client.post(_REG_URL, data)

    def test_registration_creates_pending_unverified_affiliate(self):
        resp = self._post()
        self.assertRedirects(resp, '/partner/dashboard/', fetch_redirect_response=False)
        user = User.objects.get(email='jane@example.com')
        profile = user.profile
        self.assertEqual(profile.role, Profile.Role.AFFILIATE)
        self.assertEqual(profile.affiliate_status, Profile.AffiliateStatus.PENDING)
        self.assertFalse(profile.email_verified)

    def test_registration_scopes_user_to_brand(self):
        self._post()
        user = User.objects.get(email='jane@example.com')
        self.assertEqual(user.profile.brand, self.brand)

    def test_registration_sends_verification_email(self):
        self._post()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('jane@example.com', mail.outbox[0].to)
        self.assertIn('verify-email', mail.outbox[0].body)

    def test_registration_logs_in_user(self):
        self._post()
        resp = self.client.get('/partner/dashboard/')
        self.assertEqual(resp.status_code, 200)

    def test_duplicate_email_rejected(self):
        self._post()
        self.client.logout()
        resp = self._post({'email': 'jane@example.com'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')
        self.assertEqual(User.objects.filter(email='jane@example.com').count(), 1)

    def test_password_mismatch_rejected(self):
        resp = self._post({'password2': 'different!'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'do not match')

    def test_weak_password_rejected(self):
        resp = self._post({'password1': '123', 'password2': '123'})
        self.assertEqual(resp.status_code, 200)

    def test_register_page_get_renders_form(self):
        resp = self.client.get(_REG_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'affiliate_ui/register.html')

    def test_logged_in_user_redirected_from_register(self):
        user = User.objects.create_user(username='already@x.com', email='already@x.com', password='pass')
        self.client.force_login(user)
        resp = self.client.get(_REG_URL)
        self.assertRedirects(resp, '/partner/', fetch_redirect_response=False)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTest(TestCase):
    def setUp(self):
        self.brand = _make_brand()
        self.user = User.objects.create_user(
            username='verify@example.com',
            email='verify@example.com',
            password='pass',
        )
        # Profile auto-created by signal; set PENDING + unverified
        self.user.profile.affiliate_status = Profile.AffiliateStatus.PENDING
        self.user.profile.email_verified = False
        self.user.profile.save()

    def _token(self, uid=None):
        return signing.dumps({'uid': uid or self.user.pk}, salt=_EMAIL_SALT)

    def test_valid_token_verifies_email(self):
        token = self._token()
        resp = self.client.get(f'/partner/verify-email/{token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'verified')
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.email_verified)

    def test_tampered_token_rejected(self):
        resp = self.client.get('/partner/verify-email/bad-token-xyz/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'invalid or expired')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.email_verified)

    def test_expired_token_rejected(self):
        from unittest import mock
        import time
        with mock.patch('django.core.signing.time') as mock_time:
            mock_time.time.return_value = time.time() - 90000  # 25 hours ago
            old_token = signing.dumps({'uid': self.user.pk}, salt=_EMAIL_SALT)
        resp = self.client.get(f'/partner/verify-email/{old_token}/')
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.email_verified)

    def test_idempotent_verification(self):
        token = self._token()
        self.client.get(f'/partner/verify-email/{token}/')
        resp2 = self.client.get(f'/partner/verify-email/{token}/')
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'verified')

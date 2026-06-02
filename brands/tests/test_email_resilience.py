"""Test-email button + fail-safe brand email sending.

Failures are simulated with a module-level backend that raises a *fresh*
exception each call (no reused instances), and via override_settings — both
guaranteed to restore cleanly and not leak across tests.
"""
import smtplib
import socket
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import TestCase, override_settings

from brands.email import describe_smtp_error, send_brand_mail, send_test_email
from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()
LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
FAILING = 'brands.tests.test_email_resilience.FailingBackend'


class FailingBackend(BaseEmailBackend):
    """A backend whose send raises a fresh ConnectionRefusedError every time."""
    def send_messages(self, messages):
        raise ConnectionRefusedError('connection refused')


def _configured_brand(slug, default=False):
    b = Brand.objects.create(
        slug=slug, name=f'Brand{slug}', primary_domain=f'{slug}.test',
        tracking_domain=f't.{slug}.test', is_default=default,
        smtp_host=f'smtp.{slug}.test', smtp_username='u', smtp_from_email=f'no-reply@{slug}.test')
    b.set_smtp_password('pw')
    b.save()
    return b


def _user(username, role, brand, *, is_staff=False, email=''):
    u = User.objects.create_user(username, email=email, password='pass', is_staff=is_staff)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


class DescribeSmtpErrorTest(TestCase):
    """The error mapper turns exceptions into specific, actionable reasons."""
    def test_auth(self):
        self.assertIn('Authentication failed', describe_smtp_error(smtplib.SMTPAuthenticationError(535, b'x')))

    def test_unknown_host(self):
        self.assertIn('Unknown host', describe_smtp_error(socket.gaierror('name resolution')))

    def test_timeout(self):
        self.assertIn('timed out', describe_smtp_error(TimeoutError()))

    def test_refused(self):
        self.assertIn('refused', describe_smtp_error(ConnectionRefusedError()).lower())


class SendTestEmailUnitTest(TestCase):
    def test_unconfigured_brand_returns_false(self):
        b = Brand.objects.create(slug='u', name='U', primary_domain='u.test', tracking_domain='t.u.test')
        ok, msg = send_test_email(b, 'x@u.test')
        self.assertFalse(ok)
        self.assertIn('No custom SMTP', msg)

    def test_success(self):
        b = _configured_brand('s')
        with mock.patch('brands.email.connection_for_brand', return_value=mail.get_connection(LOCMEM)):
            ok, msg = send_test_email(b, 'me@s.test')
        self.assertTrue(ok)
        self.assertIn('me@s.test', msg)
        self.assertEqual(len(mail.outbox), 1)

    def test_failure_returns_specific_reason(self):
        b = _configured_brand('f')
        with mock.patch('brands.email.connection_for_brand', return_value=FailingBackend()):
            ok, msg = send_test_email(b, 'me@f.test')
        self.assertFalse(ok)
        self.assertIn('refused', msg.lower())
        self.assertEqual(len(mail.outbox), 0)


class EmailSettingsViewTest(TestCase):
    """The view reports the test outcome inline and enforces the role."""
    def setUp(self):
        self.brand = _configured_brand('ea', default=True)
        self.admin = _user('ea_admin', Profile.Role.NETWORK_ADMIN, self.brand,
                           is_staff=True, email='admin@ea.test')
        self.manager = _user('ea_mgr', Profile.Role.AFFILIATE_MANAGER, self.brand)

    def test_success_reported_inline(self):
        self.client.force_login(self.admin)
        with mock.patch('brands.views.admin_views.send_test_email',
                        return_value=(True, 'Test email sent to admin@ea.test')):
            r = self.client.post('/admin/brands/email-settings/', {'action': 'test'}, follow=True)
        self.assertContains(r, 'Test email sent to admin@ea.test')

    def test_failure_reason_reported_inline_not_500(self):
        self.client.force_login(self.admin)
        with mock.patch('brands.views.admin_views.send_test_email',
                        return_value=(False, 'Authentication failed — check the SMTP username and password.')):
            r = self.client.post('/admin/brands/email-settings/', {'action': 'test'}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Authentication failed')

    def test_manager_blocked(self):
        self.client.force_login(self.manager)
        r = self.client.post('/admin/brands/email-settings/', {'action': 'test'})
        self.assertEqual(r.status_code, 403)


class PasswordResetResilienceTest(TestCase):
    @override_settings(EMAIL_BACKEND=FAILING)
    def test_broken_smtp_still_shows_done_page(self):
        Brand.objects.create(slug='pr', name='PR', primary_domain='pr.test',
                             tracking_domain='t.pr.test', is_default=True)
        User.objects.create_user('reset_user', email='user@pr.test', password='oldpass123')
        r = self.client.post('/partner/password-reset/', {'email': 'user@pr.test'}, HTTP_HOST='pr.test')
        # No 500 — the normal privacy-preserving done page; failure swallowed+logged.
        self.assertRedirects(r, '/partner/password-reset/done/', fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_default_backend_send_still_works(self):
        bare = Brand.objects.create(slug='def', name='Def', primary_domain='def.test',
                                    tracking_domain='t.def.test')
        self.assertEqual(send_brand_mail(bare, 'Subject', 'Body', ['x@def.test']), 1)
        self.assertEqual(len(mail.outbox), 1)


class SendBrandMailFailSafeTest(TestCase):
    @override_settings(EMAIL_BACKEND=FAILING)
    def test_send_failure_is_swallowed_not_raised(self):
        bare = Brand.objects.create(slug='fs', name='FS', primary_domain='fs.test',
                                    tracking_domain='t.fs.test')
        # fail_silently default True → returns 0, never raises (verification/approval safety).
        self.assertEqual(send_brand_mail(bare, 'S', 'B', ['x@fs.test']), 0)

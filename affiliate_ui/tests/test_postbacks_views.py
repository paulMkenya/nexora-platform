"""Tests for the affiliate-facing Postbacks self-service page — Affiliate
Inbound API spec Phase 6 (§7), plus Phase 7's SSRF guard on the URL field.
Same gating conventions as test_api_docs_views.py / test_leads_views.py:
require_approved_affiliate blocks PENDING/unverified affiliates, and every
mutation is ownership-scoped."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from leadgen.models import AffiliatePostbackConfig
from user_profile.models import Profile

User = get_user_model()

POSTBACKS_URL = '/partner/postbacks/'
CREATE_URL = '/partner/postbacks/create/'


def _approve(user):
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.save()


def _update_url(pk):
    return f'/partner/postbacks/{pk}/update/'


def _toggle_url(pk):
    return f'/partner/postbacks/{pk}/toggle-active/'


class PostbacksPageTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='pb_aff', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def test_page_200(self):
        r = self.client.get(POSTBACKS_URL)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'affiliate_ui/postbacks.html')

    def test_anonymous_redirected(self):
        self.client.logout()
        r = self.client.get(POSTBACKS_URL)
        self.assertEqual(r.status_code, 302)

    def test_shows_only_own_configs(self):
        other = User.objects.create_user(username='pb_other', password='pass')
        AffiliatePostbackConfig.objects.create(affiliate=self.user, url='https://mine.example/cb')
        AffiliatePostbackConfig.objects.create(affiliate=other, url='https://theirs.example/cb')
        r = self.client.get(POSTBACKS_URL)
        self.assertContains(r, 'mine.example')
        self.assertNotContains(r, 'theirs.example')


class PostbackCreateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='pb_create', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def test_requires_post(self):
        r = self.client.get(CREATE_URL)
        self.assertEqual(r.status_code, 405)

    def test_blank_url_shows_error(self):
        r = self.client.post(CREATE_URL, {'url': ''}, follow=True)
        messages = list(r.context['messages'])
        self.assertTrue(any('required' in str(m) for m in messages))
        self.assertFalse(AffiliatePostbackConfig.objects.exists())

    @patch('affiliate_ui.views.postbacks_views.validate_postback_url')
    def test_valid_url_creates_config_and_flashes_secret_once(self, mock_validate):
        r = self.client.post(CREATE_URL, {'url': 'https://aff.test/cb'}, follow=True)
        config = AffiliatePostbackConfig.objects.get(affiliate=self.user)
        self.assertEqual(config.url, 'https://aff.test/cb')
        messages = list(r.context['messages'])
        self.assertTrue(any(config.secret in str(m) for m in messages))

    def test_unsafe_url_is_rejected_and_never_saved(self):
        """The real, un-mocked validator runs here — a URL resolving to a
        private IP must be rejected before any row is created. 127.0.0.1
        needs no mocking since it's always a loopback address."""
        r = self.client.post(CREATE_URL, {'url': 'http://127.0.0.1/cb'}, follow=True)
        messages = list(r.context['messages'])
        self.assertTrue(any('private or internal' in str(m) for m in messages))
        self.assertFalse(AffiliatePostbackConfig.objects.exists())


class PostbackUpdateAndToggleTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='pb_update', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)
        # .objects.create() bypasses full_clean(), so the model's own
        # clean()-level SSRF check (which would reject aff.test) never
        # fires here — same as every other direct-create fixture in this
        # suite.
        self.config = AffiliatePostbackConfig.objects.create(affiliate=self.user, url='https://aff.test/cb')

    @patch('affiliate_ui.views.postbacks_views.validate_postback_url')
    def test_update_changes_url(self, mock_validate):
        r = self.client.post(_update_url(self.config.pk), {'url': 'https://aff2.test/cb'})
        self.assertEqual(r.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.url, 'https://aff2.test/cb')

    def test_update_with_unsafe_url_leaves_original_untouched(self):
        r = self.client.post(_update_url(self.config.pk), {'url': 'http://169.254.169.254/latest/meta-data/'},
                              follow=True)
        messages = list(r.context['messages'])
        self.assertTrue(any('private or internal' in str(m) for m in messages))
        self.config.refresh_from_db()
        self.assertEqual(self.config.url, 'https://aff.test/cb')

    def test_cannot_update_other_affiliates_config(self):
        other = User.objects.create_user(username='pb_other2', password='pass')
        other_config = AffiliatePostbackConfig.objects.create(affiliate=other, url='https://theirs.example/cb')
        r = self.client.post(_update_url(other_config.pk), {'url': 'https://hijacked.example/cb'})
        self.assertEqual(r.status_code, 404)

    def test_toggle_active_flips_flag(self):
        self.assertTrue(self.config.is_active)
        r = self.client.post(_toggle_url(self.config.pk))
        self.assertEqual(r.status_code, 302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_active)

    def test_cannot_toggle_other_affiliates_config(self):
        other = User.objects.create_user(username='pb_other3', password='pass')
        other_config = AffiliatePostbackConfig.objects.create(affiliate=other, url='https://theirs.example/cb')
        r = self.client.post(_toggle_url(other_config.pk))
        self.assertEqual(r.status_code, 404)

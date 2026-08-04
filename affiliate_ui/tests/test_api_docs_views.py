"""Tests for the affiliate-facing API & Docs page and key management —
Affiliate Inbound API spec Phase 5 (§6). Same gating conventions as
test_leads_views.py: require_approved_affiliate blocks PENDING/unverified
affiliates, and every mutation is ownership-scoped."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from leadgen.api_doc import build_doc_context
from public_api.models import APIKey
from user_profile.models import Profile

User = get_user_model()

DOCS_URL = '/partner/api-docs/'
PDF_URL = '/partner/api-docs/pdf/'
TEXT_URL = '/partner/api-docs/text/'
KEYS_URL = '/partner/api-docs/keys/'


def _approve(user):
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.save()


class ApiDocsPageTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='docs_aff', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def test_docs_page_200(self):
        r = self.client.get(DOCS_URL)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'affiliate_ui/api_docs.html')

    def test_anonymous_redirected(self):
        self.client.logout()
        r = self.client.get(DOCS_URL)
        self.assertEqual(r.status_code, 302)

    def test_unapproved_affiliate_blocked(self):
        pending = User.objects.create_user(username='docs_pending', password='pass')
        pending.profile.role = Profile.Role.AFFILIATE
        pending.profile.save()
        self.client.force_login(pending)
        r = self.client.get(DOCS_URL)
        self.assertEqual(r.status_code, 403)

    def test_shows_canonical_statuses_and_endpoints(self):
        r = self.client.get(DOCS_URL)
        self.assertContains(r, 'qualified_ftd')
        self.assertContains(r, '/api/leads/submit')
        self.assertContains(r, '/api/leads/statuses')

    def test_shows_own_active_key_not_others(self):
        APIKey.generate(user=self.user, name='Mine')
        other_user = User.objects.create_user(username='docs_other', password='pass')
        APIKey.generate(user=other_user, name='Not mine')
        r = self.client.get(DOCS_URL)
        self.assertContains(r, 'Mine')
        self.assertNotContains(r, 'Not mine')

    def test_pdf_export_returns_pdf_or_html_fallback(self):
        r = self.client.get(PDF_URL)
        self.assertEqual(r.status_code, 200)
        self.assertIn(r['Content-Type'], ('application/pdf', 'text/html'))

    def test_text_export_contains_key_sections(self):
        r = self.client.get(TEXT_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/plain; charset=utf-8')
        text = r.content.decode()
        assert 'ENDPOINTS' in text
        assert 'CANONICAL STATUSES' in text
        assert 'POSTBACKS' in text


class BuildDocContextTest(TestCase):
    """Anti-drift proof: the field table is introspected off the real
    serializer, not hand-copied — spec §6.3."""

    def setUp(self):
        self.user = User.objects.create_user(username='docctx_aff', password='pass')
        _approve(self.user)

    def test_field_rows_match_real_serializer(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/partner/api-docs/')
        request.user = self.user
        doc = build_doc_context(request, self.user)
        field_names = {f['name'] for f in doc['fields']}
        assert {'email', 'phone', 'offer_id', 'sub1', 'sub5'} <= field_names
        offer_id_field = next(f for f in doc['fields'] if f['name'] == 'offer_id')
        assert offer_id_field['required'] is True
        email_field = next(f for f in doc['fields'] if f['name'] == 'email')
        assert email_field['required'] is True
        sub1_field = next(f for f in doc['fields'] if f['name'] == 'sub1')
        assert sub1_field['required'] is False


class ApiKeyManagementTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='keys_aff', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def test_keys_page_200(self):
        r = self.client.get(KEYS_URL)
        self.assertEqual(r.status_code, 200)

    def test_create_key_shows_secret_once(self):
        r = self.client.post(f'{KEYS_URL}create/', {'name': 'My Integration'}, follow=True)
        key = APIKey.objects.get(user=self.user, name='My Integration')
        messages = [str(m) for m in r.context['messages']]
        assert any(key.secret in m for m in messages)

    def test_create_key_without_name_shows_error(self):
        r = self.client.post(f'{KEYS_URL}create/', {'name': ''}, follow=True)
        assert not APIKey.objects.filter(user=self.user).exists()
        messages = [str(m) for m in r.context['messages']]
        assert any('name' in m.lower() for m in messages)

    def test_regenerate_changes_secret_and_shows_new_one_once(self):
        key = APIKey.generate(user=self.user, name='Rotate me')
        old_secret = key.secret
        r = self.client.post(f'{KEYS_URL}{key.pk}/regenerate/', follow=True)
        key.refresh_from_db()
        assert key.secret != old_secret
        messages = [str(m) for m in r.context['messages']]
        assert any(key.secret in m for m in messages)

    def test_revoke_deactivates_key(self):
        key = APIKey.generate(user=self.user, name='Revoke me')
        self.client.post(f'{KEYS_URL}{key.pk}/revoke/')
        key.refresh_from_db()
        assert key.is_active is False

    def test_cannot_regenerate_another_affiliates_key(self):
        other_user = User.objects.create_user(username='keys_other', password='pass')
        other_key = APIKey.generate(user=other_user, name='Not yours')
        old_secret = other_key.secret
        r = self.client.post(f'{KEYS_URL}{other_key.pk}/regenerate/')
        assert r.status_code == 404
        other_key.refresh_from_db()
        assert other_key.secret == old_secret

    def test_cannot_revoke_another_affiliates_key(self):
        other_user = User.objects.create_user(username='keys_other2', password='pass')
        other_key = APIKey.generate(user=other_user, name='Not yours either')
        r = self.client.post(f'{KEYS_URL}{other_key.pk}/revoke/')
        assert r.status_code == 404
        other_key.refresh_from_db()
        assert other_key.is_active is True


class NavigationTest(TestCase):
    def test_api_docs_in_affiliate_nav(self):
        from nexora.navigation import nav_for
        groups = nav_for('affiliate', is_platform_owner=False)
        manage = next(g for g in groups if g.label == 'Manage')
        item_labels = [item.label for item in manage.items]
        assert 'API & Docs' in item_labels

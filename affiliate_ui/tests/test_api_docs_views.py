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


class AllThreeFormatsShareOneSourceTest(TestCase):
    """Part B's real acceptance test. Each renderer is allowed its own
    layout, but none may hold its own copy of the content — before this, the
    testing→live explainer existed twice and the two copies had already
    drifted ("Every offer starts in TESTING" vs "Every offer you send to
    starts in TESTING")."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='fmt_aff', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)

    def _all_formats(self):
        from django.test import RequestFactory

        from affiliate_ui.views.api_docs_views import api_docs_pdf

        html = self.client.get(DOCS_URL).content.decode()
        text = self.client.get(TEXT_URL).content.decode()
        # Render the PDF's own source template rather than the binary, so the
        # assertion is about content rather than PDF internals.
        request = RequestFactory().get(PDF_URL)
        request.user = self.user
        from django.template.loader import render_to_string

        from leadgen.api_doc import build_doc_context
        pdf_source = render_to_string(
            'affiliate_ui/api_docs_pdf.html', {'doc': build_doc_context(request, self.user)})
        assert api_docs_pdf  # imported to assert the view exists alongside its template
        return html, text, pdf_source

    def test_narrative_appears_in_every_format(self):
        from leadgen.api_doc import NARRATIVE

        html, text, pdf_source = self._all_formats()
        # One representative sentence per narrative section, checked in all
        # three renderings. A renderer that reintroduces its own wording fails
        # here rather than quietly disagreeing in production.
        for section, paragraphs in NARRATIVE.items():
            probe = paragraphs[0][:60]
            for name, body in (('html', html), ('text', text), ('pdf', pdf_source)):
                assert probe in body or probe.replace("'", '&#x27;') in body, \
                    f'{section} narrative missing from {name} rendering'

    def test_error_contract_appears_in_every_format(self):
        html, text, pdf_source = self._all_formats()
        for body in (html, text, pdf_source):
            assert '401' in body and '429' in body
            assert 'Invalid or inactive API key.' in body

    def test_offer_phase_appears_in_html_and_text(self):
        from offer.models import Advertiser, Offer

        from leadgen.models import AffiliateOfferLink

        adv_user = User.objects.create_user(username='fmt_adv', password='pass')
        advertiser = Advertiser.objects.create(
            user=adv_user, company='FmtAdv', email='fmt@test.com',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
        live_offer = Offer.objects.create(
            title='Fmt Live Offer', tracking_link='https://t.test/f', advertiser=advertiser)
        AffiliateOfferLink.objects.create(
            affiliate=self.user, offer=live_offer, phase=AffiliateOfferLink.PHASE_LIVE)

        html, text, _pdf = self._all_formats()
        for body in (html, text):
            assert 'Fmt Live Offer' in body
            assert 'buyer postback sets status' in body

    def test_text_export_carries_the_curl_examples(self):
        """These used to exist only in HTML, so the file an affiliate forwards
        to a traffic source had no copy-paste example in it at all."""
        _html, text, _pdf = self._all_formats()
        assert 'curl -X POST' in text
        assert '/api/leads/submit/batch' in text
        assert 'EXAMPLE REQUEST (BATCH)' in text

    def test_no_format_leaks_a_live_secret(self):
        key = APIKey.generate(user=self.user, name='Fmt key')
        for body in self._all_formats():
            assert key.secret not in body


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

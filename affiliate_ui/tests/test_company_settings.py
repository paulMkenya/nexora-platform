"""Company Settings — the affiliate's own account page.

The tier boundary is the point of this file. The page edits benign fields and
deliberately does NOT edit anything that moves money or grants access; those
keep their existing, already-guarded pages. So the tests that matter are the
ones asserting a sensitive value cannot be written from here even when it is
posted — "we just don't render an input for it" is not a control, because the
form is not what stops a hand-rolled POST.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()

SETTINGS_URL = '/partner/settings/'
SAVE_URL = '/partner/settings/save/'


def _brand():
    return Brand.objects.get_or_create(
        slug='settings-test-brand',
        defaults=dict(name='Settings Brand', primary_domain='settings.test',
                      tracking_domain='t.settings.test', is_default=False),
    )[0]


def _seed_countries():
    """Give countries_plus at least the codes these tests post.

    _apply_changes validates the submitted country against
    user_profile.geo.country_choices(), which reads countries_plus and
    degrades to an EMPTY list when that table has no rows (see its docstring —
    it must not raise during migrate). An empty list means every country fails
    validation and is silently dropped.

    Production is unaffected: countries_plus is populated there (252 rows).
    But the test database only runs migrations, and the country data is loaded
    separately, so without this the validation is being exercised against an
    empty allow-list and 'country was saved' can never pass. Seeding here keeps
    the REAL validation under test rather than weakening it to accommodate an
    empty table."""
    from countries_plus.models import Country

    # Real ISO-3166 values — iso3 and iso_numeric are both non-null on the
    # model, and country_choices() renders "Name (ISO)" from these.
    for iso, iso3, numeric, name in (
        ('KE', 'KEN', 404, 'Kenya'),
        ('MX', 'MEX', 484, 'Mexico'),
        ('US', 'USA', 840, 'United States'),
    ):
        Country.objects.get_or_create(
            iso=iso, defaults={'name': name, 'iso3': iso3, 'iso_numeric': numeric})


def _affiliate(username='settings_aff', approved=True):
    user = User.objects.create_user(
        username=username, password='pass', email=f'{username}@test.invalid',
        first_name='Ada', last_name='Lovelace')
    p = user.profile
    p.role = Profile.Role.AFFILIATE
    p.brand = _brand()
    if approved:
        p.affiliate_status = Profile.AffiliateStatus.APPROVED
        p.email_verified = True
    p.save()
    return user


class CompanySettingsAccessTest(TestCase):
    def test_anonymous_is_redirected(self):
        assert Client().get(SETTINGS_URL).status_code == 302

    def test_unapproved_affiliate_blocked(self):
        client = Client()
        client.force_login(_affiliate('settings_pending', approved=False))
        assert client.get(SETTINGS_URL).status_code == 403

    def test_approved_affiliate_sees_the_page(self):
        client = Client()
        client.force_login(_affiliate())
        r = client.get(SETTINGS_URL)
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'affiliate_ui/settings.html')

    def test_save_requires_post(self):
        client = Client()
        client.force_login(_affiliate('settings_get'))
        assert client.get(SAVE_URL).status_code == 405


class BenignFieldsAreEditableTest(TestCase):
    def setUp(self):
        _seed_countries()
        self.user = _affiliate('settings_edit')
        self.client = Client()
        self.client.force_login(self.user)

    def test_name_and_country_are_saved(self):
        self.client.post(SAVE_URL, {
            'first_name': 'Grace', 'last_name': 'Hopper', 'country': 'KE'})
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        assert (self.user.first_name, self.user.last_name) == ('Grace', 'Hopper')
        assert self.user.profile.country == 'KE'

    def test_unknown_country_is_rejected_not_stored(self):
        """Country is stamped onto leads (leads/services.py), so a junk value
        would propagate into lead data rather than sit harmlessly."""
        self.user.profile.country = 'KE'
        self.user.profile.save(update_fields=['country'])

        r = self.client.post(SAVE_URL, {
            'first_name': 'Ada', 'last_name': 'Lovelace', 'country': 'ZZ'}, follow=True)

        self.user.profile.refresh_from_db()
        assert self.user.profile.country == 'KE', 'an unrecognised country was stored'
        assert any('not recognised' in str(m) for m in r.context['messages'])

    def test_one_affiliate_cannot_edit_another(self):
        """Everything is keyed off request.user; there is no id in the form to
        tamper with, and this proves it stays that way."""
        other = _affiliate('settings_other')
        self.client.post(SAVE_URL, {
            'first_name': 'Changed', 'last_name': 'Changed', 'country': 'KE'})
        other.refresh_from_db()
        assert other.first_name == 'Ada'


class SensitiveFieldsAreNotWritableHereTest(TestCase):
    """The tier boundary. These must fail because the view refuses them, not
    because the template happens to omit an input."""

    def setUp(self):
        self.user = _affiliate('settings_sensitive')
        self.client = Client()
        self.client.force_login(self.user)

    def test_posting_an_email_change_is_ignored(self):
        """Email is the password-reset destination. With no step-up re-auth in
        this codebase, a stolen session must not be able to redirect account
        recovery."""
        original = self.user.email
        self.client.post(SAVE_URL, {
            'first_name': 'Ada', 'last_name': 'Lovelace',
            'email': 'attacker@evil.invalid'})
        self.user.refresh_from_db()
        assert self.user.email == original

    def test_posting_a_status_change_is_ignored(self):
        original = self.user.profile.affiliate_status
        self.client.post(SAVE_URL, {
            'first_name': 'Ada', 'last_name': 'Lovelace',
            'affiliate_status': Profile.AffiliateStatus.APPROVED,
            'role': Profile.Role.NETWORK_ADMIN})
        self.user.profile.refresh_from_db()
        assert self.user.profile.affiliate_status == original
        assert self.user.profile.role == Profile.Role.AFFILIATE

    def test_posting_a_brand_change_is_ignored(self):
        """Brand determines which offers the affiliate can see and submit to —
        rewriting it would be a cross-tenant move."""
        other_brand = Brand.objects.create(
            name='Other', slug='settings-other-brand',
            primary_domain='other-settings.test', tracking_domain='t.other-settings.test')
        original = self.user.profile.brand_id

        self.client.post(SAVE_URL, {
            'first_name': 'Ada', 'last_name': 'Lovelace', 'brand': other_brand.pk})

        self.user.profile.refresh_from_db()
        assert self.user.profile.brand_id == original

    def test_page_links_out_rather_than_duplicating_money_controls(self):
        """A second edit path for a money setting is how two copies drift."""
        body = self.client.get(SETTINGS_URL).content.decode()
        assert '/partner/payouts/' in body
        assert '/partner/api-docs/keys/' in body
        assert '/partner/postbacks/' in body
        # ...and no input that would write one of them from here.
        assert 'name="min_threshold"' not in body
        assert 'name="url"' not in body


class ImpersonationCannotRewriteDetailsTest(TestCase):
    def test_impersonated_session_is_refused(self):
        """Same guard as every other affiliate write: an operator acting as
        this affiliate cannot quietly change their details."""
        from unittest.mock import patch

        user = _affiliate('settings_imp')
        client = Client()
        client.force_login(user)

        with patch('impersonation.middleware.ImpersonationMiddleware._maybe_swap',
                   side_effect=lambda request: setattr(request, 'is_impersonating', True)):
            r = client.post(SAVE_URL, {
                'first_name': 'Rewritten', 'last_name': 'ByOperator', 'country': ''})

        assert r.status_code == 403
        user.refresh_from_db()
        assert user.first_name == 'Ada'


class NavigationTest(TestCase):
    def test_company_settings_is_no_longer_a_soon_placeholder(self):
        from nexora.navigation import nav_for

        groups = nav_for('affiliate', is_platform_owner=False)
        item = next(
            i for g in groups for i in g.items if i.label == 'Company Settings')
        assert item.url_name == 'affiliate_ui:company_settings', \
            'Company Settings is still a disabled SOON item'

"""Brand-only offer scoping — Paul's ruling of 2026-08-04.

An affiliate belongs to exactly ONE brand and may see, browse, submit to and
be documented for ONLY that brand's offers. There is no platform fallback: an
unbranded/shared offer reaches nobody, and the request host is irrelevant.

The point of this module is that the SAME assertion is made against all four
affiliate-facing surfaces — the API doc, the offers page, the reports filter
and the inbound API's offer_id validation — because they used to disagree
with each other (the doc followed the affiliate while browsing and submission
followed the host). Each surface now delegates to offers_for_affiliate(), so
a regression in one is a regression in all four, and this file catches it.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from affiliate_ui.views.general_views import offers_for_affiliate
from brands.models import Brand
from offer.models import Advertiser, Offer
from public_api.models import APIKey
from tracker.models import Click
from user_profile.models import Profile

User = get_user_model()

DOCS_URL = '/partner/api-docs/'
OFFERS_URL = '/partner/offers/'
REPORT_URL = '/partner/reports/daily/'
SUBMIT_URL = '/api/leads/submit'

OWN_HOST = 'brand-a.example'
OTHER_HOST = 'brand-b.example'


def _affiliate(username, brand):
    user = User.objects.create_user(username=username, password='pass')
    p = user.profile
    p.role = Profile.Role.AFFILIATE
    p.affiliate_status = Profile.AffiliateStatus.APPROVED
    p.email_verified = True
    p.brand = brand
    p.save()
    return user


def _click(affiliate, offer):
    """A click by this affiliate on this offer, so the offer qualifies for the
    reports filter's traffic-based query."""
    return Click.objects.create(
        affiliate=affiliate, offer=offer, brand=offer.brand,
        ip='127.0.0.1', revenue=0, payout=0)


@override_settings(ALLOWED_HOSTS=['*'])
class BrandOnlyOfferScopingTest(TestCase):
    def setUp(self):
        self.brand_a = Brand.objects.create(
            name='Brand A', slug='scope-a', primary_domain=OWN_HOST,
            tracking_domain='t.brand-a.example', is_default=False)
        self.brand_b = Brand.objects.create(
            name='Brand B', slug='scope-b', primary_domain=OTHER_HOST,
            tracking_domain='t.brand-b.example', is_default=True)

        adv_user = User.objects.create_user(username='scope_adv', password='pass', email='s@t.test')
        advertiser = Advertiser.objects.create(
            user=adv_user, company='ScopeAdv', email='s@t.test',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)

        self.offer_a = Offer.objects.create(
            title='BRAND A OFFER', tracking_link='https://t/a',
            brand=self.brand_a, advertiser=advertiser)
        self.offer_b = Offer.objects.create(
            title='BRAND B OFFER', tracking_link='https://t/b',
            brand=self.brand_b, advertiser=advertiser)
        self.offer_shared = Offer.objects.create(
            title='SHARED PLATFORM OFFER', tracking_link='https://t/s',
            brand=None, advertiser=advertiser)

        self.affiliate = _affiliate('scope_aff_a', self.brand_a)
        self.key = APIKey.generate(user=self.affiliate, name='Scope key', requests_per_hour=1000)

    # ---------- the four surfaces, same assertion ----------

    def _surface_bodies(self, host):
        """The three HTML surfaces, fetched through `host`."""
        c = Client()
        c.force_login(self.affiliate)
        return {
            'api doc': c.get(DOCS_URL, HTTP_HOST=host).content.decode(),
            'offers page': c.get(OFFERS_URL, HTTP_HOST=host).content.decode(),
            'reports filter': c.get(REPORT_URL, HTTP_HOST=host).content.decode(),
        }

    def _submit(self, offer_id, host, tag='x'):
        """A distinct email/source_id per call: submitting the same consumer
        twice inside the dedupe window returns the ORIGINAL lead with 200, not
        a fresh 201, which would otherwise look like a scoping failure."""
        tag = ''.join(ch for ch in tag if ch.isalnum() or ch == '-')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'ApiKey {self.key.secret}')
        return client.post(SUBMIT_URL, {
            'email': f'scope-{tag}@test.com', 'phone': '+15551234567',
            'offer_id': offer_id, 'source_id': f'src-{tag}',
        }, format='json', HTTP_HOST=host)

    def test_all_four_surfaces_show_only_own_brand_on_both_hosts(self):
        # Traffic to every offer, so the reports filter has something to show
        # and can only be narrowed by the scoping rule, not by absence of data.
        for offer in (self.offer_a, self.offer_b, self.offer_shared):
            _click(self.affiliate, offer)

        for host in (OWN_HOST, OTHER_HOST):
            for surface, body in self._surface_bodies(host).items():
                assert 'BRAND A OFFER' in body, f'{surface} via {host}: own offer missing'
                assert 'BRAND B OFFER' not in body, f'{surface} via {host}: OTHER BRAND leaked'
                assert 'SHARED PLATFORM OFFER' not in body, f'{surface} via {host}: SHARED leaked'

            # Surface 4: the inbound API's offer_id validation.
            assert self._submit(self.offer_a.pk, host, tag=f'own-{host}').status_code == 201, \
                f'api submit via {host}: own offer rejected'
            for blocked, label in ((self.offer_b.pk, 'other brand'), (self.offer_shared.pk, 'shared')):
                resp = self._submit(blocked, host, tag=f'{label}-{host}')
                assert resp.status_code == 400, f'api submit via {host}: {label} offer accepted'
                assert 'does not resolve' in str(resp.data), \
                    f'api submit via {host}: wrong error for {label} offer'

    def test_host_does_not_change_what_is_visible(self):
        """Host is irrelevant now — the two hosts must agree exactly."""
        own = self._surface_bodies(OWN_HOST)
        other = self._surface_bodies(OTHER_HOST)
        for surface in own:
            assert ('BRAND A OFFER' in own[surface]) == ('BRAND A OFFER' in other[surface])
            assert ('BRAND B OFFER' in own[surface]) == ('BRAND B OFFER' in other[surface])

    def test_shared_offer_reaches_nobody(self):
        """Not 'available to everyone' — available to no one, on any surface."""
        for host in (OWN_HOST, OTHER_HOST):
            for surface, body in self._surface_bodies(host).items():
                assert 'SHARED PLATFORM OFFER' not in body, f'{surface} via {host}'
        assert self.offer_shared not in offers_for_affiliate(self.affiliate)

    def test_cannot_open_another_brands_offer_detail(self):
        c = Client()
        c.force_login(self.affiliate)
        for host in (OWN_HOST, OTHER_HOST):
            for offer in (self.offer_b, self.offer_shared):
                r = c.get(f'/partner/offers/{offer.pk}/', HTTP_HOST=host)
                assert r.status_code == 404, f'offer {offer.pk} reachable via {host}'

    def test_reports_filter_keeps_history_when_an_advertiser_goes_away(self):
        """Reporting looks backwards. Suspending the advertiser must not erase
        an affiliate's own earnings history from the filter — availability
        governs what you may newly send to, not what you already sent. Brand
        isolation still applies, which the sibling assertions below prove."""
        _click(self.affiliate, self.offer_a)
        advertiser = self.offer_a.advertiser
        advertiser.advertiser_status = Advertiser.AdvertiserStatus.SUSPENDED
        advertiser.save(update_fields=['advertiser_status'])

        c = Client()
        c.force_login(self.affiliate)
        reports = c.get(REPORT_URL, HTTP_HOST=OWN_HOST).content.decode()
        assert 'BRAND A OFFER' in reports, 'own history vanished from the reports filter'
        assert 'BRAND B OFFER' not in reports, 'other brand leaked into reports'
        assert 'SHARED PLATFORM OFFER' not in reports, 'shared offer leaked into reports'

        # ...while the forward-looking surfaces DO drop it, because a
        # suspended advertiser's offer is no longer one you may send to.
        assert self.offer_a not in offers_for_affiliate(self.affiliate)
        assert self._submit(self.offer_a.pk, OWN_HOST, tag='suspended').status_code == 400

    def test_curl_example_uses_a_brand_owned_offer(self):
        from django.test import RequestFactory

        from leadgen.api_doc import build_doc_context

        request = RequestFactory().get(DOCS_URL, HTTP_HOST=OTHER_HOST)
        request.user = self.affiliate
        doc = build_doc_context(request, self.affiliate)
        assert doc['examples']['offer_id_used'] == self.offer_a.pk
        assert [o['id'] for o in doc['offers']] == [self.offer_a.pk]


@override_settings(ALLOWED_HOSTS=['*'])
class ZeroOfferAffiliateTest(TestCase):
    """An affiliate whose brand has no offers, and an affiliate with no brand
    at all (prod has one: the `admin` superuser carries role=AFFILIATE). Both
    get the empty state — never a shared offer as filler."""

    def setUp(self):
        self.empty_brand = Brand.objects.create(
            name='Empty', slug='scope-empty', primary_domain='empty.example',
            tracking_domain='t.empty.example', is_default=True)
        adv_user = User.objects.create_user(username='zero_adv', password='pass', email='z@t.test')
        advertiser = Advertiser.objects.create(
            user=adv_user, company='ZeroAdv', email='z@t.test',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
        self.shared = Offer.objects.create(
            title='SHARED PLATFORM OFFER', tracking_link='https://t/s',
            brand=None, advertiser=advertiser)

    def _doc_for(self, user):
        c = Client()
        c.force_login(user)
        return c.get(DOCS_URL, HTTP_HOST='empty.example').content.decode()

    def test_brand_with_no_offers_gets_the_empty_state(self):
        body = self._doc_for(_affiliate('zero_aff', self.empty_brand))
        assert 'No offers assigned yet' in body
        assert 'SHARED PLATFORM OFFER' not in body

    def test_brandless_affiliate_gets_nothing(self):
        """Paul's option (a): a brandless affiliate matches no brand, and must
        NOT fall through to the unbranded set."""
        brandless = _affiliate('brandless_aff', None)
        assert list(offers_for_affiliate(brandless)) == []
        body = self._doc_for(brandless)
        assert 'No offers assigned yet' in body
        assert 'SHARED PLATFORM OFFER' not in body

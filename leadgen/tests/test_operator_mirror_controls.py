"""Tests for Phase 6 of the Affiliate Inbound API spec — the operator
mirror controls on the Distribution console: flipping a lead's canonical
status from the Leads console (leadgen/admin_views.py::lead_status_flip),
and the Affiliate Integrations page for viewing/flipping each (affiliate,
offer) pair's testing/live phase (affiliate_offer_links_list,
affiliate_offer_link_go_live, affiliate_offer_link_revert).

Brand scoping conventions mirror test_console.py exactly — this is a
sibling surface on the same console."""
import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from leadgen import canonical_status
from leadgen.models import AffiliateOfferLink, Lead, LeadStatusEvent
from user_profile.models import Profile

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


def _operator(brand):
    user = User.objects.create_user(username=f'mirror_op_{brand.slug}', password='pass', is_staff=True)
    user.profile.role = Profile.Role.NETWORK_ADMIN
    user.profile.brand = brand
    user.profile.save()
    return user


def _owner():
    return User.objects.create_superuser(username='mirror_owner', email='o@test.com', password='pass')


@pytest.fixture
def brand_a(db):
    return _brand('mirror-a')


@pytest.fixture
def brand_b(db):
    return _brand('mirror-b')


@pytest.fixture
def affiliate(db, brand_a):
    user = User.objects.create_user(username='mirror_affiliate', password='pass', email='maff@test.com')
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.brand = brand_a
    user.profile.save()
    return user


@pytest.fixture
def offer_a(db, brand_a):
    from offer.models import Advertiser, Offer
    adv_user = User.objects.create_user(username='mirror_adv_a', password='pass', email='madv-a@test.com')
    adv = Advertiser.objects.create(user=adv_user, brand=brand_a, company='MirrorAdvA', email='madv-a@test.com')
    return Offer.objects.create(
        title='Mirror Offer A', tracking_link='https://t.mirror-a.test/click', brand=brand_a, advertiser=adv)


@pytest.fixture
def offer_b(db, brand_b):
    from offer.models import Advertiser, Offer
    adv_user = User.objects.create_user(username='mirror_adv_b', password='pass', email='madv-b@test.com')
    adv = Advertiser.objects.create(user=adv_user, brand=brand_b, company='MirrorAdvB', email='madv-b@test.com')
    return Offer.objects.create(
        title='Mirror Offer B', tracking_link='https://t.mirror-b.test/click', brand=brand_b, advertiser=adv)


@pytest.fixture
def lead_a(db, brand_a, affiliate, offer_a):
    return Lead.objects.create(
        intake_channel=Lead.CHANNEL_AFFILIATE_API, brand=brand_a,
        affiliate=affiliate, offer=offer_a,
        email='mirror-lead-a@test.com', phone='+15559990000',
    )


@pytest.fixture
def link_a(db, affiliate, offer_a):
    """AffiliateOfferLink rows are created lazily — only the first time a
    status is actually applied for a (affiliate, offer) pair (see
    status_sync.resolve_affiliate_offer_link) — never just from a Lead
    existing. Tests that need one already in place create it directly,
    same as any other fixture data."""
    return AffiliateOfferLink.objects.create(affiliate=affiliate, offer=offer_a)


@pytest.mark.django_db
class TestLeadStatusFlip:
    def test_requires_post(self, client, brand_a, lead_a):
        client.force_login(_operator(brand_a))
        r = client.get(f'/admin/distribution/leads/{lead_a.pk}/status/')
        assert r.status_code == 405

    def test_anonymous_redirected(self, client, lead_a):
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': canonical_status.FTD})
        assert r.status_code == 302

    def test_operator_flips_status_in_testing_phase(self, client, brand_a, lead_a):
        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': canonical_status.FTD})
        assert r.status_code == 302
        lead_a.refresh_from_db()
        assert lead_a.canonical_status == canonical_status.FTD
        assert LeadStatusEvent.objects.filter(lead=lead_a, to_status=canonical_status.FTD,
                                               source=LeadStatusEvent.SOURCE_OPERATOR).exists()

    def test_invalid_status_shows_error_and_does_not_write(self, client, brand_a, lead_a):
        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': 'not-a-real-status'},
                         follow=True)
        messages = list(r.context['messages'])
        assert any('valid status' in str(m) for m in messages)
        assert not LeadStatusEvent.objects.filter(lead=lead_a).exists()

    def test_operator_cannot_flip_other_brands_lead(self, client, brand_a, brand_b, lead_a):
        client.force_login(_operator(brand_b))
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': canonical_status.FTD})
        assert r.status_code == 404
        lead_a.refresh_from_db()
        assert lead_a.canonical_status != canonical_status.FTD

    def test_flip_once_live_without_override_reason_shows_authority_error(self, client, brand_a, lead_a, link_a):
        link_a.phase = AffiliateOfferLink.PHASE_LIVE
        link_a.save(update_fields=['phase'])
        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': canonical_status.FTD},
                         follow=True)
        messages = list(r.context['messages'])
        assert any('override' in str(m).lower() for m in messages)

    def test_flip_once_live_with_override_reason_succeeds(self, client, brand_a, lead_a, link_a):
        link_a.phase = AffiliateOfferLink.PHASE_LIVE
        link_a.save(update_fields=['phase'])
        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {
            'to_status': canonical_status.FTD, 'override_reason': 'buyer feed was stuck, confirmed manually',
        })
        assert r.status_code == 302
        lead_a.refresh_from_db()
        assert lead_a.canonical_status == canonical_status.FTD


@pytest.mark.django_db
class TestAffiliateOfferLinksConsole:
    def test_operator_sees_only_own_brand_links(self, client, brand_a, brand_b, link_a, affiliate, offer_b):
        other_affiliate = User.objects.create_user(username='mirror_aff_b', password='pass', email='mab@test.com')
        other_affiliate.profile.role = Profile.Role.AFFILIATE
        other_affiliate.profile.brand = brand_b
        other_affiliate.profile.save()
        AffiliateOfferLink.objects.create(affiliate=other_affiliate, offer=offer_b)

        client.force_login(_operator(brand_a))
        r = client.get('/admin/distribution/affiliate-links/')
        assert r.status_code == 200
        assert str(affiliate) in r.content.decode()
        assert str(other_affiliate) not in r.content.decode()

    def test_owner_sees_all_brands_links(self, client, brand_a, brand_b, link_a, affiliate, offer_b):
        other_affiliate = User.objects.create_user(username='mirror_aff_b2', password='pass', email='mab2@test.com')
        other_affiliate.profile.role = Profile.Role.AFFILIATE
        other_affiliate.profile.brand = brand_b
        other_affiliate.profile.save()
        AffiliateOfferLink.objects.create(affiliate=other_affiliate, offer=offer_b)

        client.force_login(_owner())
        r = client.get('/admin/distribution/affiliate-links/')
        body = r.content.decode()
        assert str(affiliate) in body
        assert str(other_affiliate) in body

    def test_flip_creates_link_defaulting_to_testing_and_it_shows_up(self, client, brand_a, lead_a):
        """No link exists yet for this pair — flipping a status is what
        creates the row (via resolve_affiliate_offer_link), and it should
        default to TESTING and immediately show up on the console."""
        assert not AffiliateOfferLink.objects.filter(affiliate=lead_a.affiliate, offer=lead_a.offer).exists()
        client.force_login(_operator(brand_a))
        client.post(f'/admin/distribution/leads/{lead_a.pk}/status/', {'to_status': canonical_status.FTD})
        link = AffiliateOfferLink.objects.get(affiliate=lead_a.affiliate, offer=lead_a.offer)
        assert link.phase == AffiliateOfferLink.PHASE_TESTING
        r = client.get('/admin/distribution/affiliate-links/')
        assert r.status_code == 200
        assert 'Testing' in r.content.decode()

    def test_go_live_requires_post(self, client, brand_a, link_a):
        client.force_login(_operator(brand_a))
        r = client.get(f'/admin/distribution/affiliate-links/{link_a.pk}/go-live/')
        assert r.status_code == 405

    def test_go_live_flips_phase_and_stamps_actor(self, client, brand_a, link_a):
        operator = _operator(brand_a)
        client.force_login(operator)
        r = client.post(f'/admin/distribution/affiliate-links/{link_a.pk}/go-live/')
        assert r.status_code == 302
        link_a.refresh_from_db()
        assert link_a.phase == AffiliateOfferLink.PHASE_LIVE
        assert link_a.phase_changed_by_id == operator.pk

    def test_revert_flips_phase_back_to_testing(self, client, brand_a, link_a):
        link_a.phase = AffiliateOfferLink.PHASE_LIVE
        link_a.save(update_fields=['phase'])
        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/affiliate-links/{link_a.pk}/revert/')
        assert r.status_code == 302
        link_a.refresh_from_db()
        assert link_a.phase == AffiliateOfferLink.PHASE_TESTING

    def test_operator_cannot_go_live_other_brands_link(self, client, brand_a, brand_b, lead_a, offer_b):
        other_affiliate = User.objects.create_user(username='mirror_aff_b3', password='pass', email='mab3@test.com')
        other_affiliate.profile.role = Profile.Role.AFFILIATE
        other_affiliate.profile.brand = brand_b
        other_affiliate.profile.save()
        other_link = AffiliateOfferLink.objects.create(affiliate=other_affiliate, offer=offer_b)

        client.force_login(_operator(brand_a))
        r = client.post(f'/admin/distribution/affiliate-links/{other_link.pk}/go-live/')
        assert r.status_code == 404
        other_link.refresh_from_db()
        assert other_link.phase == AffiliateOfferLink.PHASE_TESTING


@pytest.mark.django_db
def test_navigation_includes_affiliate_integrations():
    """nexora/navigation.py registry check — Phase 6 adds a new Distribution
    nav item alongside the pre-existing Leads/Buyers/Routing Rules trio."""
    from nexora.navigation import nav_for
    groups = nav_for('admin', is_platform_owner=True)
    distribution = next(g for g in groups if g.label == 'Distribution')
    item_labels = [item.label for item in distribution.items]
    assert item_labels == ['Leads', 'Buyers', 'Routing Rules', 'Affiliate Integrations']

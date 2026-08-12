"""My Leads filtering, search and pagination.

The page was a hard [:200] slice with no filters, so an affiliate with more
leads than that could not reach the rest and had no way to find one lead by
email or tracking id. The pull API has had this filtering since it shipped;
this brings the page to parity.

The tests that matter most are the ownership ones. Filtering adds a lot of
new query parameters, and every one of them is a chance to widen a queryset
that must never widen — so the interesting cases are the ones that TRY to
reach another affiliate's leads through a filter and must still come back
empty.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from brands.models import Brand
from leadgen.models import Lead
from user_profile.models import Profile

User = get_user_model()

LEADS_URL = '/partner/leads/'


def _brand(slug='filter-test-brand'):
    return Brand.objects.get_or_create(
        slug=slug,
        defaults=dict(name='Filter Brand', primary_domain=f'{slug}.test',
                      tracking_domain=f't.{slug}.test', is_default=False),
    )[0]


def _affiliate(username, brand=None):
    user = User.objects.create_user(
        username=username, password='pass', email=f'{username}@test.invalid')
    p = user.profile
    p.role = Profile.Role.AFFILIATE
    p.brand = brand or _brand()
    p.affiliate_status = Profile.AffiliateStatus.APPROVED
    p.email_verified = True
    p.save()
    return user


def _lead(affiliate, **kw):
    defaults = dict(
        brand=affiliate.profile.brand,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        affiliate=affiliate,
        email='consumer@example.com',
        phone='+15550000000',
    )
    defaults.update(kw)
    return Lead.objects.create(**defaults)


class OwnershipHoldsUnderEveryFilterTest(TestCase):
    """A filter must never be a way to see someone else's leads. Each of these
    posts a value that MATCHES the other affiliate's lead exactly."""

    def setUp(self):
        self.me = _affiliate('filter_me')
        self.them = _affiliate('filter_them')
        self.their_lead = _lead(
            self.them, email='theirs@example.com', phone='+15559999999',
            source_id='their-source', canonical_status='ftd')
        self.client = Client()
        self.client.force_login(self.me)

    def _ids_on_page(self, **params):
        r = self.client.get(LEADS_URL, params)
        assert r.status_code == 200
        return [lead.pk for lead in r.context['leads']]

    def test_unfiltered_does_not_leak(self):
        assert self.their_lead.pk not in self._ids_on_page()

    def test_search_matching_their_email_does_not_leak(self):
        assert self._ids_on_page(q='theirs@example.com') == []

    def test_search_matching_their_phone_does_not_leak(self):
        assert self._ids_on_page(q='15559999999') == []

    def test_source_id_matching_theirs_does_not_leak(self):
        assert self._ids_on_page(source_id='their-source') == []

    def test_status_matching_theirs_does_not_leak(self):
        assert self._ids_on_page(status='ftd') == []

    def test_date_range_covering_theirs_does_not_leak(self):
        today = timezone.now().date().isoformat()
        assert self._ids_on_page(date_from='2000-01-01', date_to=today) == []


class FilteringTest(TestCase):
    def setUp(self):
        self.user = _affiliate('filter_user')
        self.client = Client()
        self.client.force_login(self.user)
        self.ftd = _lead(self.user, email='alice@example.com',
                         source_id='src-alpha', canonical_status='ftd')
        self.pending = _lead(self.user, email='bob@example.com', phone='+15551234567',
                             source_id='src-beta', canonical_status='pending')
        self.rejected = _lead(self.user, email='carol@example.com',
                              source_id='src-gamma', status=Lead.STATUS_REJECTED)

    def _ids(self, **params):
        return [lead.pk for lead in self.client.get(LEADS_URL, params).context['leads']]

    def test_no_filter_returns_everything(self):
        assert set(self._ids()) == {self.ftd.pk, self.pending.pk, self.rejected.pk}

    def test_status_filters_on_canonical_status(self):
        assert self._ids(status='ftd') == [self.ftd.pk]

    def test_delivery_filters_on_internal_status(self):
        assert self._ids(delivery=Lead.STATUS_REJECTED) == [self.rejected.pk]

    def test_search_matches_email(self):
        assert self._ids(q='alice@') == [self.ftd.pk]

    def test_search_matches_phone(self):
        assert self._ids(q='1234567') == [self.pending.pk]

    def test_search_matches_source_id(self):
        assert self._ids(q='src-beta') == [self.pending.pk]

    def test_source_id_is_exact_not_partial(self):
        """source_id mirrors the pull API, where it is an exact match. Partial
        matching belongs to `q`; having both behave the same would make one of
        them pointless."""
        assert self._ids(source_id='src-') == []
        assert self._ids(source_id='src-beta') == [self.pending.pk]

    def test_filters_combine_as_and_not_or(self):
        assert self._ids(status='ftd', q='alice@') == [self.ftd.pk]
        assert self._ids(status='ftd', q='bob@') == []

    def test_unknown_status_is_ignored_not_an_error(self):
        """Same posture as the pull API, which drops an unparseable
        updated_since rather than 400ing. A filter box is not a validation
        surface."""
        r = self.client.get(LEADS_URL, {'status': 'not-a-real-status'})
        assert r.status_code == 200
        assert len(r.context['leads']) == 3

    def test_unparseable_date_is_ignored_not_an_error(self):
        r = self.client.get(LEADS_URL, {'date_from': 'yesterday-ish'})
        assert r.status_code == 200
        assert len(r.context['leads']) == 3

    def test_date_range_bounds_are_inclusive(self):
        old = _lead(self.user, email='old@example.com')
        Lead.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=10))
        cutoff = (timezone.now() - timedelta(days=10)).date().isoformat()
        assert old.pk in self._ids(date_from=cutoff, date_to=cutoff)


class PaginationTest(TestCase):
    def setUp(self):
        self.user = _affiliate('filter_pager')
        self.client = Client()
        self.client.force_login(self.user)
        self.leads = [_lead(self.user, email=f'lead{i}@example.com') for i in range(120)]

    def test_first_page_is_capped_at_page_size(self):
        from affiliate_ui.views.leads_views import PAGE_SIZE

        r = self.client.get(LEADS_URL)
        assert len(r.context['leads']) == PAGE_SIZE
        assert r.context['paginator'].count == 120

    def test_later_pages_are_reachable(self):
        """The point of the change: before this, leads past the [:200] slice
        were unreachable from the UI entirely."""
        r = self.client.get(LEADS_URL, {'page': 3})
        assert r.status_code == 200
        assert r.context['page_obj'].number == 3
        assert len(r.context['leads']) == 20

    def test_pages_do_not_overlap_and_cover_everything(self):
        seen = []
        for page in (1, 2, 3):
            seen += [lead.pk for lead in self.client.get(LEADS_URL, {'page': page}).context['leads']]
        assert len(seen) == len(set(seen)) == 120

    def test_out_of_range_page_clamps_instead_of_erroring(self):
        r = self.client.get(LEADS_URL, {'page': 999})
        assert r.status_code == 200
        assert r.context['page_obj'].number == r.context['paginator'].num_pages

    def test_junk_page_clamps_instead_of_erroring(self):
        r = self.client.get(LEADS_URL, {'page': 'banana'})
        assert r.status_code == 200
        assert r.context['page_obj'].number == 1

    def test_filters_survive_paging(self):
        r = self.client.get(LEADS_URL, {'q': 'lead1', 'page': 2})
        assert r.status_code == 200
        assert 'q=lead1' in r.context['filter_querystring']
        assert 'page' not in r.context['filter_querystring']


class InjectPreservesFiltersTest(TestCase):
    def test_empty_buyer_id_is_refused_not_a_500(self):
        """A blank select or a hand-rolled POST used to reach
        get_object_or_404(pk=''), which raises ValueError from the field's
        get_prep_value — a 500, not a 404. Malformed input must be refused."""
        user = _affiliate('filter_inject')
        client = Client()
        client.force_login(user)
        lead = _lead(user)

        r = client.post('/partner/leads/inject/', {
            'buyer_id': '', 'lead_ids': [lead.pk],
            'filter_querystring': 'status=ftd&q=alice',
        })
        assert r.status_code == 302
        assert 'status=ftd' in r['Location']

    def test_non_numeric_buyer_id_is_refused_not_a_500(self):
        user = _affiliate('filter_inject_junk')
        client = Client()
        client.force_login(user)
        lead = _lead(user)

        r = client.post('/partner/leads/inject/', {
            'buyer_id': 'abc', 'lead_ids': [lead.pk],
        })
        assert r.status_code == 302

    def test_no_selection_returns_to_the_filtered_view(self):
        user = _affiliate('filter_inject_none')
        brand = user.profile.brand
        from leadgen.models import BoxType, LeadBuyer

        box = BoxType.objects.create(name='B', slug='filter-box')
        buyer = LeadBuyer.objects.create(
            brand=brand, box_type=box, name='Buyer', slug='filter-buyer',
            is_active=True, base_url='https://b.test')
        client = Client()
        client.force_login(user)

        r = client.post('/partner/leads/inject/', {
            'buyer_id': buyer.pk, 'lead_ids': [],
            'filter_querystring': 'status=ftd&q=alice',
        })
        assert r.status_code == 302
        assert 'status=ftd' in r['Location']
        assert 'q=alice' in r['Location']


class EmptyStateTest(TestCase):
    def test_no_matches_is_distinguished_from_no_leads(self):
        """A filter with no hits must not read as 'you have never submitted a
        lead' — that is alarming and false."""
        user = _affiliate('filter_empty')
        _lead(user, email='real@example.com')
        client = Client()
        client.force_login(user)

        r = client.get(LEADS_URL, {'q': 'nothing-matches-this'})
        assert r.status_code == 200
        body = r.content.decode()
        assert 'No leads match these filters' in body
        assert 'No leads submitted yet' not in body

    def test_genuinely_empty_says_so(self):
        user = _affiliate('filter_really_empty')
        client = Client()
        client.force_login(user)
        r = client.get(LEADS_URL)
        assert 'No leads submitted yet' in r.content.decode()

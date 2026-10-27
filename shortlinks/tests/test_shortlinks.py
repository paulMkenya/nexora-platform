"""Affiliate short links: readable /go/<slug> URLs that record a normal click."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from offer.models import ACTIVE_STATUS, PAUSED_STATUS, Offer
from offer.tasks.cache_offers import cache_offers
from shortlinks.models import ShortLink
from shortlinks.services import short_url, slug_error, suggest_slug
from user_profile.models import Profile

User = get_user_model()
HOST = 'app.brand-s.example'


def _affiliate(username, brand, approved=True):
    user = User.objects.create_user(username=username, password='pass')
    p = user.profile
    p.role = Profile.Role.AFFILIATE
    p.affiliate_status = Profile.AffiliateStatus.APPROVED if approved else Profile.AffiliateStatus.PENDING
    p.email_verified = True
    p.brand = brand
    p.save()
    return user


@override_settings(ALLOWED_HOSTS=['*'])
class ShortLinkTests(TestCase):

    def setUp(self):
        self.brand = Brand.objects.create(
            name='Brand S', slug='brand-s', primary_domain=HOST,
            tracking_domain='track.brand-s.example', is_default=False)
        self.aff = _affiliate('ambikesh@example.com', self.brand)
        self.offer = Offer.objects.create(
            title='TheGameIO KE (MVAS)', brand=self.brand, status=ACTIVE_STATUS,
            tracking_link='https://adv.example/click?click_id={click_id}')
        cache_offers()
        self.client.force_login(self.aff)

    def _link(self, **kw):
        return ShortLink.objects.create(
            **dict(dict(slug='ambikesh-thegameio', affiliate=self.aff, offer=self.offer), **kw))

    # ── naming ──────────────────────────────────────────────────────────

    def test_suggested_slug_is_readable_and_unique(self):
        self.assertEqual(suggest_slug(self.aff, self.offer), 'ambikesh-thegameio-ke-mvas')
        self._link(slug='ambikesh-thegameio-ke-mvas')
        self.assertEqual(suggest_slug(self.aff, self.offer), 'ambikesh-thegameio-ke-mvas-2')

    def test_slug_rules(self):
        self._link(slug='taken-name')
        self.assertIn('already taken', slug_error('taken-name'))
        self.assertIn('reserved', slug_error('admin'))
        self.assertTrue(slug_error('ab'))
        self.assertTrue(slug_error('-bad-'))
        self.assertEqual(slug_error('good-name-1'), '')

    def test_url_uses_the_offer_brand_tracking_domain(self):
        self.assertEqual(short_url(self._link()), 'https://track.brand-s.example/go/ambikesh-thegameio')

    # ── redirect ────────────────────────────────────────────────────────

    @mock.patch('tracker.views.click_task')
    def test_go_records_a_click_and_redirects(self, click_task):
        link = self._link(sub1='fb-campaign')
        r = self.client.get('/go/ambikesh-thegameio', HTTP_HOST='track.brand-s.example')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('https://adv.example/click?click_id='))
        data = click_task.delay.call_args[0][0]
        self.assertEqual((data['offer_id'], data['pid'], data['sub1']), (self.offer.id, self.aff.id, 'fb-campaign'))
        self.assertIn(data['click_id'], r['Location'])
        link.refresh_from_db()
        self.assertEqual(link.clicks, 1)
        self.assertIsNotNone(link.last_click_at)

    @mock.patch('tracker.views.click_task')
    def test_query_subs_override_stored_ones(self, click_task):
        self._link(sub1='stored', sub2='keep')
        self.client.get('/go/ambikesh-thegameio?sub1=placement-7')
        data = click_task.delay.call_args[0][0]
        self.assertEqual((data['sub1'], data['sub2']), ('placement-7', 'keep'))

    @mock.patch('tracker.views.click_task')
    def test_dead_links_404_without_recording(self, click_task):
        self._link(is_active=False)
        self.assertEqual(self.client.get('/go/ambikesh-thegameio').status_code, 404)
        self.assertEqual(self.client.get('/go/no-such-link').status_code, 404)
        ShortLink.objects.update(is_active=True)
        Offer.objects.filter(pk=self.offer.pk).update(status=PAUSED_STATUS)
        self.assertEqual(self.client.get('/go/ambikesh-thegameio').status_code, 404)
        self.assertFalse(click_task.delay.called)

    @mock.patch('tracker.views.click_task')
    def test_suspended_affiliate_link_404s(self, click_task):
        self._link()
        Profile.objects.filter(user=self.aff).update(affiliate_status=Profile.AffiliateStatus.SUSPENDED)
        self.assertEqual(self.client.get('/go/ambikesh-thegameio').status_code, 404)

    # ── partner portal ──────────────────────────────────────────────────

    def test_create_from_portal(self):
        r = self.client.post('/partner/links/create/', {'offer': self.offer.id, 'slug': 'My Game Link', 'sub1': 'x'},
                             HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 302)
        link = ShortLink.objects.get()
        self.assertEqual((link.slug, link.affiliate, link.sub1), ('my-game-link', self.aff, 'x'))

    def test_blank_name_uses_suggestion(self):
        self.client.post('/partner/links/create/', {'offer': self.offer.id, 'slug': ''}, HTTP_HOST=HOST)
        self.assertEqual(ShortLink.objects.get().slug, 'ambikesh-thegameio-ke-mvas')

    def test_cannot_link_another_brands_offer(self):
        other = Brand.objects.create(name='Other', slug='other-b', primary_domain='o.example',
                                     tracking_domain='t.o.example', is_default=False)
        foreign = Offer.objects.create(title='Foreign', brand=other, status=ACTIVE_STATUS, tracking_link='https://x')
        self.client.post('/partner/links/create/', {'offer': foreign.id, 'slug': 'sneaky'}, HTTP_HOST=HOST)
        self.assertFalse(ShortLink.objects.exists())

    def test_cannot_touch_another_affiliates_link(self):
        other = _affiliate('other@example.com', self.brand)
        link = self._link(affiliate=other)
        for action in ('update', 'toggle-active', 'delete'):
            r = self.client.post(f'/partner/links/{link.pk}/{action}/', {'slug': 'hijack'}, HTTP_HOST=HOST)
            self.assertEqual(r.status_code, 404)
        link.refresh_from_db()
        self.assertEqual((link.slug, link.is_active), ('ambikesh-thegameio', True))

    def test_page_lists_links_and_offer_detail_shows_them(self):
        self._link()
        page = self.client.get('/partner/links/', HTTP_HOST=HOST).content.decode()
        self.assertIn('https://track.brand-s.example/go/ambikesh-thegameio', page)
        detail = self.client.get(f'/partner/offers/{self.offer.id}/', HTTP_HOST=HOST).content.decode()
        self.assertIn('/go/ambikesh-thegameio', detail)

    def test_pending_affiliate_is_gated(self):
        self.client.force_login(_affiliate('new@example.com', self.brand, approved=False))
        self.assertNotEqual(self.client.get('/partner/links/', HTTP_HOST=HOST).status_code, 200)

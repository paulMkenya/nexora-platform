"""Tests for the affiliate-facing My Leads page at /partner/leads/ — list
view gating, and the inject action's ownership scoping (an affiliate must
never be able to inject another affiliate's lead by id-tampering)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings

from leadgen.models import Lead, LeadBuyer, LeadInjection
from user_profile.models import Profile

User = get_user_model()
CACHES_DUMMY = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}


def _approve(user):
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.save()


@override_settings(CACHES=CACHES_DUMMY)
class MyLeadsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='leads_aff', password='pass')
        _approve(self.user)
        self.client.force_login(self.user)
        self.buyer = LeadBuyer.objects.create(
            name='Test Buyer', slug='test-buyer-affui', is_active=True,
            base_url='https://buyer.test',
        )

    def test_leads_page_200(self):
        r = self.client.get('/partner/leads/')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'affiliate_ui/leads.html')

    def test_leads_page_anonymous_redirect(self):
        self.client.logout()
        r = self.client.get('/partner/leads/')
        self.assertEqual(r.status_code, 302)

    def test_unapproved_affiliate_blocked(self):
        pending = User.objects.create_user(username='pending_aff', password='pass')
        pending.profile.role = Profile.Role.AFFILIATE
        pending.profile.save()
        self.client.force_login(pending)
        r = self.client.get('/partner/leads/')
        self.assertEqual(r.status_code, 403)

    def test_own_leads_listed(self):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=self.user,
            email='mine@test.com', phone='+15551234567',
        )
        r = self.client.get('/partner/leads/')
        self.assertContains(r, str(lead.pk))

    @patch('leadgen.services.inject_lead_task')
    def test_inject_own_lead_creates_injection(self, mock_task):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=self.user,
            email='mine@test.com', phone='+15551234567',
        )
        r = self.client.post('/partner/leads/inject/', {
            'buyer_id': str(self.buyer.pk), 'lead_ids': [str(lead.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(LeadInjection.objects.filter(lead=lead, buyer=self.buyer).exists())
        mock_task.assert_called_once()

    @patch('leadgen.services.inject_lead_task')
    def test_cannot_inject_another_affiliates_lead(self, mock_task):
        other = User.objects.create_user(username='other_aff', password='pass')
        other.profile.role = Profile.Role.AFFILIATE
        other.profile.save()
        other_lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=other,
            email='not-mine@test.com', phone='+15551234567',
        )
        r = self.client.post('/partner/leads/inject/', {
            'buyer_id': str(self.buyer.pk), 'lead_ids': [str(other_lead.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(LeadInjection.objects.filter(lead=other_lead).exists())
        mock_task.assert_not_called()

    @patch('leadgen.services.inject_lead_task')
    def test_mixed_own_and_others_only_injects_own(self, mock_task):
        other = User.objects.create_user(username='other_aff2', password='pass')
        other.profile.role = Profile.Role.AFFILIATE
        other.profile.save()
        my_lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=self.user,
            email='mine2@test.com', phone='+15551234567',
        )
        other_lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=other,
            email='not-mine2@test.com', phone='+15551234567',
        )
        self.client.post('/partner/leads/inject/', {
            'buyer_id': str(self.buyer.pk), 'lead_ids': [str(my_lead.pk), str(other_lead.pk)],
        })
        self.assertTrue(LeadInjection.objects.filter(lead=my_lead).exists())
        self.assertFalse(LeadInjection.objects.filter(lead=other_lead).exists())

    def test_inject_requires_post(self):
        r = self.client.get('/partner/leads/inject/')
        self.assertEqual(r.status_code, 405)

    def test_inject_no_leads_selected_shows_error(self):
        r = self.client.post('/partner/leads/inject/', {'buyer_id': str(self.buyer.pk)}, follow=True)
        messages = list(r.context['messages'])
        self.assertTrue(any('Select at least one' in str(m) for m in messages))

    def test_inject_invalid_buyer_404s(self):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=self.user,
            email='mine3@test.com', phone='+15551234567',
        )
        r = self.client.post('/partner/leads/inject/', {
            'buyer_id': '999999', 'lead_ids': [str(lead.pk)],
        })
        self.assertEqual(r.status_code, 404)

    def test_cannot_inject_to_other_brands_buyer(self):
        from brands.models import Brand
        other_brand = Brand.objects.update_or_create(
            slug='other-brand-leadgen-test',
            defaults=dict(name='Other Brand', primary_domain='other.test', tracking_domain='t.other.test'),
        )[0]
        scoped_buyer = LeadBuyer.objects.create(
            brand=other_brand, name='Other Brand Buyer', slug='other-brand-buyer',
            is_active=True, base_url='https://other-buyer.test',
        )
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=self.user,
            email='mine4@test.com', phone='+15551234567',
        )
        r = self.client.post('/partner/leads/inject/', {
            'buyer_id': str(scoped_buyer.pk), 'lead_ids': [str(lead.pk)],
        })
        # request.brand is unset/None in this test client, so a buyer scoped
        # to a DIFFERENT brand must not resolve as available.
        self.assertEqual(r.status_code, 404)

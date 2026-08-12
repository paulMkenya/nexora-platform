"""The lead detail page — leadgen.admin_views.lead_detail.

Two things matter here beyond "it renders": that it is brand-scoped like every
other console surface, and that it does not put injection payloads on screen.
Responses are filtered default-deny by ``sanitize_response_for_audit`` at write
time, but rows written before that landed can still hold a buyer credential, so
the page must not render them regardless of what a given row happens to
contain.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from brands.models import Brand
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection, RoutingRule

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


class LeadDetailTest(TestCase):
    def setUp(self):
        self.brand = _brand('ld-a')
        self.other = _brand('ld-b')
        self.box_type = BoxType.objects.create(
            name='LD Box', slug='ld-box',
            connector_class='leadgen.connectors.LeadBuyerConnector',
            auth_type=BoxType.AUTH_API_KEY_QUERY, auth_param_name='apiKey',
            single_endpoint_path='/leads', batch_endpoint_path='',
            fetch_endpoint_path='/leads', batch_max_size=1,
            rate_limit_burst=10, rate_limit_refill_tokens=1, rate_limit_refill_seconds=1,
        )
        self.buyer = LeadBuyer.objects.create(
            brand=self.brand, box_type=self.box_type, name='Primary', slug='ld-primary',
            is_active=True, base_url='https://primary.test',
        )
        self.lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand,
            email='ld@test.com', phone='+15551230000', first_name='Ada', last_name='Lovelace',
        )
        self.owner = User.objects.create_superuser('ld-owner', 'owner@ld.test', 'pw')
        self.operator = User.objects.create_user('ld-op', 'op@ld.test', 'pw', is_staff=True)
        self.operator.profile.brand = self.brand
        self.operator.profile.save()

        self.url = reverse('leadgen_console:lead_detail', args=[self.lead.pk])

    def test_requires_staff(self):
        assert self.client.get(self.url).status_code == 302

    def test_renders_the_lead(self):
        self.client.force_login(self.operator)
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'leadgen/console/lead_detail.html')
        self.assertContains(response, 'Ada')
        self.assertContains(response, 'ld@test.com')

    def test_another_brands_lead_is_not_reachable(self):
        theirs = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.other,
            email='theirs@test.com', phone='+15559990000',
        )
        self.client.force_login(self.operator)
        response = self.client.get(reverse('leadgen_console:lead_detail', args=[theirs.pk]))
        assert response.status_code == 404

    def test_platform_owner_reaches_any_brand(self):
        theirs = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.other,
            email='theirs@test.com', phone='+15559990000',
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse('leadgen_console:lead_detail', args=[theirs.pk]))
        assert response.status_code == 200

    def test_injection_payloads_are_never_rendered(self):
        LeadInjection.objects.create(
            lead=self.lead, buyer=self.buyer, status=LeadInjection.STATUS_DELIVERED,
            external_id='EXT-1',
            request_payload={'password': 'sup3rsecret-request'},
            response_payload={'redirectUrl': 'https://broker.test/auto?token=leaked-bearer'},
        )
        self.client.force_login(self.operator)
        response = self.client.get(self.url)
        body = response.content.decode()

        assert 'sup3rsecret-request' not in body
        assert 'leaked-bearer' not in body
        # The useful, safe part of the same row is still shown.
        assert 'EXT-1' in body

    def test_latency_is_shown_only_for_delivered_attempts(self):
        delivered = LeadInjection.objects.create(
            lead=self.lead, buyer=self.buyer, status=LeadInjection.STATUS_DELIVERED,
        )
        delivered.delivered_at = delivered.created_at + datetime.timedelta(milliseconds=250)
        delivered.save(update_fields=['delivered_at'])
        LeadInjection.objects.create(
            lead=self.lead, buyer=self.buyer, status=LeadInjection.STATUS_FAILED,
        )

        self.client.force_login(self.operator)
        response = self.client.get(self.url)

        latencies = [i.latency_ms for i in response.context['injections']]
        assert latencies == [250, None]

    def test_planned_chain_marks_which_buyers_were_tried(self):
        RoutingRule.objects.create(
            brand=self.brand, buyer=self.buyer, name='catch-all', priority=1, is_active=True,
        )
        LeadInjection.objects.create(
            lead=self.lead, buyer=self.buyer, status=LeadInjection.STATUS_FAILED,
        )
        self.client.force_login(self.operator)
        response = self.client.get(self.url)

        chain = response.context['planned_chain']
        assert [step['buyer'].pk for step in chain] == [self.buyer.pk]
        assert chain[0]['attempted'] is True

    def test_no_matching_rule_gives_an_empty_chain_not_an_error(self):
        self.client.force_login(self.operator)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['planned_chain'] == []
        assert response.context['delivered_to'] is None

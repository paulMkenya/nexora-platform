"""Tests for the public, unauthenticated landing-page capture view
(leadgen/public_views.py) — honeypot, per-IP rate limit (fail-open), and
lead creation for direct FB/Google ad traffic."""
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client

from leadgen.models import Lead
from leadgen.public_views import RATE_LIMIT_MAX


@pytest.mark.django_db
class TestCaptureLead:
    def setup_method(self):
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def test_get_renders_form(self, offer):
        client = Client()
        resp = client.get(f'/l/{offer.pk}/')
        assert resp.status_code == 200

    def test_get_unknown_offer_404s(self, db):
        client = Client()
        resp = client.get('/l/999999/')
        assert resp.status_code == 404

    def test_valid_post_creates_lead(self, offer):
        client = Client()
        with patch('leadgen.public_views.maybe_auto_inject'):
            resp = client.post(f'/l/{offer.pk}/', {
                'first_name': 'Jane', 'last_name': 'Doe',
                'email': 'jane@test.com', 'phone': '+15551234567',
            })
        assert resp.status_code == 200
        lead = Lead.objects.get(email='jane@test.com')
        assert lead.intake_channel == Lead.CHANNEL_LANDING_PAGE
        assert lead.affiliate_id is None
        assert lead.offer_id == offer.pk
        assert lead.brand_id == offer.brand_id

    def test_invalid_data_returns_400_no_lead(self, offer):
        client = Client()
        resp = client.post(f'/l/{offer.pk}/', {'email': 'not-an-email', 'phone': 'x'})
        assert resp.status_code == 400
        assert not Lead.objects.filter(offer=offer).exists()

    def test_honeypot_tripped_looks_like_success_but_creates_no_lead(self, offer):
        client = Client()
        resp = client.post(f'/l/{offer.pk}/', {
            'email': 'bot@test.com', 'phone': '+15551234567', 'hp_check': 'i-am-a-bot',
        })
        assert resp.status_code == 200
        assert not Lead.objects.filter(email='bot@test.com').exists()

    def test_rate_limit_blocks_after_max_per_ip(self, offer):
        client = Client()
        with patch('leadgen.public_views.maybe_auto_inject'):
            for i in range(RATE_LIMIT_MAX):
                resp = client.post(f'/l/{offer.pk}/', {
                    'email': f'lead{i}@test.com', 'phone': '+15551234567',
                }, REMOTE_ADDR='10.0.0.5')
                assert resp.status_code == 200

            resp = client.post(f'/l/{offer.pk}/', {
                'email': 'over-limit@test.com', 'phone': '+15551234567',
            }, REMOTE_ADDR='10.0.0.5')
        assert resp.status_code == 429
        assert not Lead.objects.filter(email='over-limit@test.com').exists()

    def test_rate_limit_is_per_ip(self, offer):
        client = Client()
        with patch('leadgen.public_views.maybe_auto_inject'):
            for i in range(RATE_LIMIT_MAX):
                client.post(f'/l/{offer.pk}/', {
                    'email': f'ip1-{i}@test.com', 'phone': '+15551234567',
                }, REMOTE_ADDR='10.0.0.6')

            # Different IP is unaffected by the first IP's exhausted bucket.
            resp = client.post(f'/l/{offer.pk}/', {
                'email': 'ip2@test.com', 'phone': '+15551234567',
            }, REMOTE_ADDR='10.0.0.7')
        assert resp.status_code == 200
        assert Lead.objects.filter(email='ip2@test.com').exists()

    def test_rate_limit_fails_open_when_cache_unavailable(self, offer):
        client = Client()
        with patch('leadgen.public_views.cache.add', side_effect=Exception('cache down')), \
             patch('leadgen.public_views.maybe_auto_inject'):
            resp = client.post(f'/l/{offer.pk}/', {
                'email': 'fail-open@test.com', 'phone': '+15551234567',
            })
        assert resp.status_code == 200
        assert Lead.objects.filter(email='fail-open@test.com').exists()

    def test_submission_triggers_maybe_auto_inject(self, offer):
        client = Client()
        with patch('leadgen.public_views.maybe_auto_inject') as mock_inject:
            client.post(f'/l/{offer.pk}/', {'email': 'a@test.com', 'phone': '+15551234567'})
        mock_inject.assert_called_once()

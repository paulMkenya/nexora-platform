"""Tests for tasks.geolocate_lead — the best-effort, on-create IP ->
country_iso2 lookup. Never allowed to raise or block lead capture; every
failure mode (no token, no IP, lookup error, lead already resolved) must
be a silent no-op."""
from unittest.mock import patch

import pytest

from ext.ipstack.api import Err, Response, TimeoutErr
from leadgen.models import Lead
from leadgen.tasks import geolocate_lead


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='geo@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestGeolocateLead:
    def test_no_token_is_a_noop(self, settings):
        settings.IPSTACK_TOKEN = ''
        lead = _lead(ip='8.8.8.8')
        with patch('ext.ipstack.api.API.lookup') as mock_lookup:
            geolocate_lead(lead.pk)
        mock_lookup.assert_not_called()
        lead.refresh_from_db()
        assert lead.country_iso2 == ''

    def test_no_ip_is_a_noop(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip=None)
        with patch('ext.ipstack.api.API.lookup') as mock_lookup:
            geolocate_lead(lead.pk)
        mock_lookup.assert_not_called()

    def test_already_resolved_is_a_noop(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8', country_iso2='US')
        with patch('ext.ipstack.api.API.lookup') as mock_lookup:
            geolocate_lead(lead.pk)
        mock_lookup.assert_not_called()

    def test_successful_lookup_sets_country(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8')
        with patch('ext.ipstack.api.API.lookup', return_value=Response(ip='8.8.8.8', country_code='US')):
            geolocate_lead(lead.pk)
        lead.refresh_from_db()
        assert lead.country_iso2 == 'US'

    def test_err_from_lookup_does_not_raise_or_set(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8')
        with patch('ext.ipstack.api.API.lookup', side_effect=Err()):
            geolocate_lead(lead.pk)  # must not raise
        lead.refresh_from_db()
        assert lead.country_iso2 == ''

    def test_timeout_err_does_not_raise_or_set(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8')
        with patch('ext.ipstack.api.API.lookup', side_effect=TimeoutErr()):
            geolocate_lead(lead.pk)  # must not raise — TimeoutErr is an Err
        lead.refresh_from_db()
        assert lead.country_iso2 == ''

    def test_unexpected_exception_does_not_raise(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8')
        with patch('ext.ipstack.api.API.lookup', side_effect=ValueError('unexpected')):
            geolocate_lead(lead.pk)  # must not raise
        lead.refresh_from_db()
        assert lead.country_iso2 == ''

    def test_missing_lead_is_a_noop(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        geolocate_lead(999999)  # must not raise

    def test_never_overwrites_existing_value(self, settings):
        settings.IPSTACK_TOKEN = 'fake-token'
        lead = _lead(ip='8.8.8.8', country_iso2='CA')
        with patch('ext.ipstack.api.API.lookup', return_value=Response(ip='8.8.8.8', country_code='US')):
            geolocate_lead(lead.pk)
        lead.refresh_from_db()
        assert lead.country_iso2 == 'CA'

"""Tests for leadgen model-level behavior not already exercised by the
connector/task/API tests: LeadBuyer's encrypted-secret helpers and
supports_batch property, Lead's full_name/__str__."""
import pytest

from leadgen.models import Lead, LeadBuyer


@pytest.mark.django_db
class TestLeadBuyerSecret:
    def test_set_then_get_api_key_round_trips(self, buyer):
        buyer.set_api_key('brand-new-secret')
        buyer.save(update_fields=['api_key_encrypted'])
        assert buyer.get_api_key() == 'brand-new-secret'

    def test_api_key_stored_encrypted_not_plaintext(self, buyer):
        buyer.set_api_key('plaintext-secret')
        assert 'plaintext-secret' not in buyer.api_key_encrypted


@pytest.mark.django_db
class TestSupportsBatch:
    def test_supports_batch_true_when_size_over_one_and_path_set(self, buyer):
        buyer.batch_max_size = 50
        buyer.batch_endpoint_path = '/leads/batch'
        assert buyer.supports_batch is True

    def test_supports_batch_false_when_size_is_one(self, buyer):
        buyer.batch_max_size = 1
        assert buyer.supports_batch is False

    def test_supports_batch_false_when_no_batch_path(self, buyer):
        buyer.batch_max_size = 50
        buyer.batch_endpoint_path = ''
        assert buyer.supports_batch is False


@pytest.mark.django_db
class TestLeadFullName:
    def test_full_name_joins_first_and_last(self):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            first_name='Jane', last_name='Doe', email='jane@test.com', phone='+15551234567',
        )
        assert lead.full_name == 'Jane Doe'

    def test_full_name_strips_when_last_name_blank(self):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            first_name='Jane', email='jane@test.com', phone='+15551234567',
        )
        assert lead.full_name == 'Jane'

    def test_str_includes_name_and_email(self):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            first_name='Jane', email='jane@test.com', phone='+15551234567',
        )
        assert 'Jane' in str(lead)
        assert 'jane@test.com' in str(lead)

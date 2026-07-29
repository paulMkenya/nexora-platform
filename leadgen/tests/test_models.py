"""Tests for leadgen model-level behavior not already exercised by the
connector/task/API tests: LeadBuyer's encrypted-secret helpers and
supports_batch property, Lead's full_name/__str__, and Phase 4's Box
Registry (BoxType / get_effective_field_mapping)."""
import pytest

from leadgen.models import BoxType, Lead, LeadBuyer


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
    """supports_batch reads box_type.batch_max_size/batch_endpoint_path as
    of Phase 4 (the Box Registry) — same batch capability for every buyer
    instance on a platform, not something a brand customizes per-buyer."""

    def test_supports_batch_true_when_size_over_one_and_path_set(self, buyer):
        buyer.box_type.batch_max_size = 50
        buyer.box_type.batch_endpoint_path = '/leads/batch'
        assert buyer.supports_batch is True

    def test_supports_batch_false_when_size_is_one(self, buyer):
        buyer.box_type.batch_max_size = 1
        assert buyer.supports_batch is False

    def test_supports_batch_false_when_no_batch_path(self, buyer):
        buyer.box_type.batch_max_size = 50
        buyer.box_type.batch_endpoint_path = ''
        assert buyer.supports_batch is False

    def test_supports_batch_false_when_no_box_type(self, brand):
        buyer = LeadBuyer.objects.create(
            brand=brand, name='No Box', slug='no-box-buyer', is_active=True,
            base_url='https://nobox.test')
        assert buyer.supports_batch is False


@pytest.mark.django_db
class TestBoxTypeFieldMapping:
    """get_effective_field_mapping() is what the connector actually reads
    (see connectors.py::_map_field) — box_type.default_field_mapping is the
    platform-wide template, buyer.field_mapping is the per-brand override,
    instance wins on key collision."""

    def test_merges_box_type_defaults_with_instance_overrides(self, buyer):
        buyer.box_type.default_field_mapping = {'firstname': 'FName', 'lastname': 'LName'}
        buyer.box_type.save(update_fields=['default_field_mapping'])
        buyer.field_mapping = {'lastname': 'Surname'}  # overrides the box_type default
        buyer.save(update_fields=['field_mapping'])

        mapping = buyer.get_effective_field_mapping()
        assert mapping == {'firstname': 'FName', 'lastname': 'Surname'}

    def test_falls_back_to_bare_field_mapping_when_no_box_type(self, brand):
        buyer = LeadBuyer.objects.create(
            brand=brand, name='No Box', slug='no-box-mapping', is_active=True,
            base_url='https://nobox.test', field_mapping={'email': 'Mail'})
        assert buyer.get_effective_field_mapping() == {'email': 'Mail'}

    def test_instance_mapping_empty_falls_through_to_box_type_defaults(self, buyer):
        buyer.box_type.default_field_mapping = {'email': 'EmailAddress'}
        buyer.box_type.save(update_fields=['default_field_mapping'])
        buyer.field_mapping = {}
        buyer.save(update_fields=['field_mapping'])

        assert buyer.get_effective_field_mapping() == {'email': 'EmailAddress'}


@pytest.mark.django_db
class TestBoxTypeRegistrySharing:
    """The whole point of Phase 4: two LeadBuyer instances on the same
    BoxType share its platform-level config, and changing the shared
    BoxType affects both without touching either LeadBuyer row."""

    def test_two_buyers_share_one_box_type_config(self, brand, box_type):
        other_brand_buyer = LeadBuyer.objects.create(
            brand=brand, box_type=box_type, name='Second Instance',
            slug='second-instance-buyer', is_active=True, base_url='https://second.test')
        assert other_brand_buyer.box_type_id == box_type.pk
        assert other_brand_buyer.supports_batch == (box_type.batch_max_size > 1 and bool(box_type.batch_endpoint_path))

    def test_updating_shared_box_type_affects_every_instance(self, buyer, brand, box_type):
        second = LeadBuyer.objects.create(
            brand=brand, box_type=box_type, name='Second', slug='shared-box-second',
            is_active=True, base_url='https://second.test')
        box_type.batch_max_size = 200
        box_type.save(update_fields=['batch_max_size'])

        buyer.refresh_from_db()
        second.refresh_from_db()
        assert buyer.box_type.batch_max_size == 200
        assert second.box_type.batch_max_size == 200


@pytest.mark.django_db
class TestGetConnector:
    """get_connector() resolves box_type.connector_class via Django's
    import_string — declarative selection, never eval'd code (see
    connectors.py module docstring)."""

    def test_resolves_default_connector_class(self, buyer):
        from leadgen.connectors import LeadBuyerConnector, get_connector

        connector = get_connector(buyer)
        assert isinstance(connector, LeadBuyerConnector)
        assert connector.buyer == buyer
        assert connector.box_type == buyer.box_type

    def test_resolves_a_custom_connector_class_from_box_type(self, buyer):
        from leadgen.connectors import LeadBuyerConnector, get_connector

        buyer.box_type.connector_class = 'leadgen.connectors.LeadBuyerConnector'
        buyer.box_type.save(update_fields=['connector_class'])
        connector = get_connector(buyer)
        assert isinstance(connector, LeadBuyerConnector)

    def test_bad_connector_class_path_raises(self, buyer):
        from django.utils.module_loading import import_string

        from leadgen.connectors import get_connector

        buyer.box_type.connector_class = 'leadgen.connectors.NotARealConnector'
        buyer.box_type.save(update_fields=['connector_class'])
        with pytest.raises(ImportError):
            get_connector(buyer)
        # sanity check the exception really comes from import_string's own resolution
        with pytest.raises(ImportError):
            import_string(buyer.box_type.connector_class)


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

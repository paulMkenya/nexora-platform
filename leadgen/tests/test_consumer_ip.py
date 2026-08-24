"""The consumer IP must be the CONSUMER's, or absent — never a stand-in.

WHAT WENT WRONG. `_create_lead` fell back to `request.META['REMOTE_ADDR']`
whenever an affiliate did not supply `ip`. Behind nginx-proxy-manager that is
the PROXY's Docker bridge address, so every such lead was stamped 172.18.0.7
and forwarded to the buyer as the consumer's IP: identical on every lead, in
RFC1918 space, and contradicting a `geo` on the other side of the world. The
buyer reads that as fraud, and the affiliate wears it.

The fallback was wrong even with a perfect proxy chain: on the affiliate API
the connecting peer is the affiliate's SERVER. There is no arrangement of
headers that turns it into the consumer.

Two layers are tested here, because one is not enough:
  * INTAKE filters what we store (security.public_consumer_ip).
  * EGRESS filters what we send (LeadBuyerConnector.consumer_ip), which also
    covers rows written before the intake filter existed.
"""
import pytest

from leadgen.models import Lead
from leadgen.security import public_consumer_ip


class TestPublicConsumerIP:
    @pytest.mark.parametrize('value', [
        '172.18.0.7',      # the exact address that caused this
        '10.0.0.4', '192.168.1.10', '127.0.0.1',
        '169.254.169.254',  # cloud metadata
        '::1', 'fd00::1',
        '', None, 'not-an-ip', 'localhost',
    ])
    def test_unusable_values_become_none(self, value):
        assert public_consumer_ip(value) is None

    @pytest.mark.parametrize('value', ['192.0.2.1', '198.51.100.1', '203.0.113.45'])
    def test_documentation_ranges_are_rejected(self, value):
        """RFC 5737 addresses are what people paste out of API examples. They
        are not routable, so as a consumer IP they are a fiction — and one
        that would travel to the buyer looking like a real claim."""
        assert public_consumer_ip(value) is None

    def test_carrier_grade_nat_is_rejected(self):
        """100.64.0.0/10 is the specific reason this uses `is_global` rather
        than the SSRF predicate: CGNAT is not an SSRF concern and passes
        _is_unsafe_ip, but it identifies nobody. A mobile consumer's usable
        address is their carrier's public egress, never this."""
        assert public_consumer_ip('100.64.0.1') is None

    @pytest.mark.parametrize('value', ['82.77.237.108', '177.17.161.18', '2a02:26f7::1'])
    def test_real_public_addresses_pass_through(self, value):
        assert public_consumer_ip(value) == value

    def test_surrounding_whitespace_is_tolerated(self):
        assert public_consumer_ip('  82.77.237.108 ') == '82.77.237.108'


@pytest.mark.django_db
class TestEgressGuard:
    """A bad IP already in the table must not reach a buyer."""

    def _hypernet(self, brand):
        from leadgen.connectors import HypernetConnector
        from leadgen.models import BoxType, LeadBuyer

        box = BoxType.objects.create(
            name='Hypernet', slug='hypernet-ip',
            connector_class='leadgen.connectors.HypernetConnector',
            auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
            single_endpoint_path='/api/external/integration/lead',
            default_field_mapping={'email': 'profile.email', 'phone': 'profile.phone'},
        )
        buyer = LeadBuyer.objects.create(
            brand=brand, box_type=box, name='H', slug='hypernet-ip',
            base_url='https://box.test', extra_payload_fields={'funnel': 'f'},
        )
        return HypernetConnector(buyer)

    def test_the_proxy_address_is_not_forwarded(self, brand):
        lead = Lead.objects.create(
            brand=brand, first_name='A', last_name='B', email='a@b.test',
            phone='+447700900123', country_iso2='PL', ip='172.18.0.7',
        )
        payload = self._hypernet(brand).build_payload(lead)
        assert 'ip' not in payload, (
            'a private address reached the buyer as a consumer IP — this is the '
            'fraud signal the guard exists to stop')
        assert payload.get('geo') == 'PL', 'dropping a bad ip must not disturb geo'

    def test_a_real_consumer_address_is_forwarded(self, brand):
        lead = Lead.objects.create(
            brand=brand, first_name='A', last_name='B', email='a@b.test',
            phone='+447700900123', country_iso2='PL', ip='82.77.237.108',
        )
        assert self._hypernet(brand).build_payload(lead)['ip'] == '82.77.237.108'

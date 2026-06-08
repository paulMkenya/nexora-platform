"""Tests for crypto address validators and provider dispatch."""
from django.test import TestCase, override_settings

from payouts.crypto.validators import validate_address, SUPPORTED_NETWORKS, explorer_url


class AddressValidationTest(TestCase):
    # EVM addresses
    def test_valid_evm_address(self):
        addr = '0xAbCdEf1234567890AbCdEf1234567890AbCdEf12'
        for net in ['ETH', 'USDC-ERC20', 'USDC-Polygon', 'USDT-Polygon', 'USDC-Base']:
            with self.subTest(network=net):
                self.assertTrue(validate_address(net, addr))

    def test_invalid_evm_short(self):
        self.assertFalse(validate_address('ETH', '0xABCDEF'))

    def test_invalid_evm_no_prefix(self):
        self.assertFalse(validate_address('ETH', 'AbCdEf1234567890AbCdEf1234567890AbCdEf12'))

    def test_invalid_evm_too_long(self):
        self.assertFalse(validate_address('ETH', '0x' + 'a' * 42))

    # TRON addresses
    def test_valid_tron_address(self):
        # Valid base58 (no 0, O, I, l chars) 34-char TRON address
        self.assertTrue(validate_address('USDT-TRC20', 'TFCpPHCMaRzYFKcb7KfBaqupFMLJRPtqXz'))

    def test_invalid_tron_wrong_start(self):
        self.assertFalse(validate_address('USDT-TRC20', 'ARX1234567890123456789012345678901'))

    def test_invalid_tron_too_short(self):
        self.assertFalse(validate_address('USDT-TRC20', 'T12345'))

    # BTC addresses
    def test_valid_btc_bech32(self):
        self.assertTrue(validate_address('BTC', 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq'))

    def test_valid_btc_legacy_p2pkh(self):
        self.assertTrue(validate_address('BTC', '1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf'))

    def test_valid_btc_legacy_p2sh(self):
        self.assertTrue(validate_address('BTC', '3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy'))

    def test_invalid_btc(self):
        self.assertFalse(validate_address('BTC', 'notabtcaddress'))

    # Edge cases
    def test_empty_address(self):
        self.assertFalse(validate_address('ETH', ''))

    def test_empty_network(self):
        self.assertFalse(validate_address('', '0xAbCdEf1234567890AbCdEf1234567890AbCdEf12'))

    def test_unknown_network(self):
        self.assertFalse(validate_address('UNKNOWN', '0xAbCdEf1234567890AbCdEf1234567890AbCdEf12'))

    def test_supported_networks_list(self):
        self.assertIn('USDT-TRC20', SUPPORTED_NETWORKS)
        self.assertIn('ETH', SUPPORTED_NETWORKS)
        self.assertIn('BTC', SUPPORTED_NETWORKS)

    def test_explorer_url_eth(self):
        url = explorer_url('ETH', '0xabc123')
        self.assertIn('etherscan.io', url)
        self.assertIn('0xabc123', url)

    def test_explorer_url_tron(self):
        url = explorer_url('USDT-TRC20', 'txid123')
        self.assertIn('tronscan.org', url)

    def test_explorer_url_unknown(self):
        self.assertEqual(explorer_url('UNKNOWN', 'txid'), '')


@override_settings(CRYPTO_PAYOUT_PROVIDER='nowpayments')
class ProviderSwitchTest(TestCase):
    def test_get_crypto_provider_nowpayments(self):
        from payouts.providers.dispatch import get_crypto_provider
        from payouts.providers.nowpayments import NowPaymentsPayoutClient
        self.assertIsInstance(get_crypto_provider(), NowPaymentsPayoutClient)

    @override_settings(CRYPTO_PAYOUT_PROVIDER='self_custodial')
    def test_unknown_provider_fails_loud(self):
        # self_custodial was removed; any non-allowlisted value must raise, never
        # silently route on this money path.
        from django.core.exceptions import ImproperlyConfigured
        from payouts.providers.dispatch import get_crypto_provider
        with self.assertRaises(ImproperlyConfigured):
            get_crypto_provider()

    @override_settings(CRYPTO_PAYOUT_PROVIDER='typo-provider')
    def test_typo_provider_fails_loud(self):
        from django.core.exceptions import ImproperlyConfigured
        from payouts.providers.dispatch import get_crypto_provider
        with self.assertRaises(ImproperlyConfigured):
            get_crypto_provider()

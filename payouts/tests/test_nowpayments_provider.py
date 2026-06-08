"""Unit tests for the NOWPayments Mass Payouts client.

Every HTTP call is mocked — CI must never touch the network. Covers: the mainnet
guard, JWT caching, the single 401-refresh-retry, amount formatting to 6 dp, the
single-entry withdrawals array, response parsing for each method, and
NowPaymentsError on non-2xx. The preflight command is tested only with a fully
mocked client (no network).
"""
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from payouts.providers.nowpayments import NowPaymentsError, NowPaymentsPayoutClient
from payouts.providers.nowpayments.payouts import format_amount

SANDBOX_URL = 'https://api-sandbox.nowpayments.io/v1'
PROD_URL = 'https://api.nowpayments.io/v1'


def _resp(status=200, json_data=None, content=b'{}'):
    """Build a fake requests.Response-like mock."""
    m = mock.Mock()
    m.status_code = status
    m.ok = 200 <= status < 300
    m.content = content
    m.text = '' if content is None else (content.decode() if isinstance(content, bytes) else str(content))
    m.json.return_value = {} if json_data is None else json_data
    return m


def _client(**kwargs):
    """A client with injected dummy creds — never reads real settings/env."""
    defaults = dict(
        api_key='dummy-key', email='dummy@example.com', password='dummy-pass',
        base_url=SANDBOX_URL, allow_mainnet=False, totp_secret='JBSWY3DPEHPK3PXP',
        ipn_callback_url='https://hook.example.com/ipn',
    )
    defaults.update(kwargs)
    return NowPaymentsPayoutClient(**defaults)


class MainnetGuardTest(SimpleTestCase):
    def test_production_url_without_flag_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            _client(base_url=PROD_URL, allow_mainnet=False)

    def test_production_url_with_flag_allowed(self):
        # Explicit opt-in builds without raising.
        client = _client(base_url=PROD_URL, allow_mainnet=True)
        self.assertTrue(client.base_url.endswith('nowpayments.io/v1'))

    def test_unknown_host_treated_as_production(self):
        with self.assertRaises(ImproperlyConfigured):
            _client(base_url='https://evil.example.com/v1', allow_mainnet=False)

    def test_sandbox_url_builds(self):
        client = _client()
        self.assertEqual(client.base_url, SANDBOX_URL)

    def test_empty_base_url_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            _client(base_url='')


class AmountFormattingTest(SimpleTestCase):
    def test_truncates_to_six_dp(self):
        self.assertEqual(format_amount(Decimal('1.23456789')), '1.234567')

    def test_integer_has_no_exponent(self):
        self.assertEqual(format_amount(Decimal('10')), '10')

    def test_trailing_zeros_stripped(self):
        self.assertEqual(format_amount(Decimal('10.50')), '10.5')

    def test_accepts_float_and_str(self):
        self.assertEqual(format_amount('2.5'), '2.5')
        self.assertEqual(format_amount(3), '3')

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            format_amount(Decimal('-1'))

    def test_six_dp_exact(self):
        self.assertEqual(format_amount(Decimal('0.123456')), '0.123456')


class JwtAuthTest(SimpleTestCase):
    @mock.patch('payouts.providers.nowpayments.base.requests.post')
    def test_jwt_cached_after_first_fetch(self, post):
        post.return_value = _resp(json_data={'token': 'tok-123'})
        client = _client()
        self.assertEqual(client._get_jwt(), 'tok-123')
        self.assertEqual(client._get_jwt(), 'tok-123')
        post.assert_called_once()  # cached — only one /auth call

    @mock.patch('payouts.providers.nowpayments.base.requests.post')
    def test_auth_failure_raises(self, post):
        post.return_value = _resp(status=401, content=b'{"message":"bad creds"}')
        client = _client()
        with self.assertRaises(NowPaymentsError) as ctx:
            client._get_jwt()
        self.assertEqual(ctx.exception.status_code, 401)

    @mock.patch('payouts.providers.nowpayments.base.requests.post')
    def test_missing_token_in_response_raises(self, post):
        post.return_value = _resp(json_data={'not_token': 'x'})
        with self.assertRaises(NowPaymentsError):
            _client()._get_jwt()

    def test_missing_creds_raises(self):
        client = _client(email='', password='')
        with self.assertRaises(NowPaymentsError):
            client._get_jwt()


class RequestRetryTest(SimpleTestCase):
    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    @mock.patch('payouts.providers.nowpayments.base.requests.post')
    def test_401_refreshes_jwt_and_retries_once(self, post, request):
        post.side_effect = [
            _resp(json_data={'token': 'tok-old'}),
            _resp(json_data={'token': 'tok-new'}),
        ]
        request.side_effect = [
            _resp(status=401, content=b'{"message":"expired"}'),
            _resp(status=200, json_data={'ok': True}),
        ]
        client = _client()
        result = client.get_balance()
        self.assertEqual(result, {'ok': True})
        self.assertEqual(request.call_count, 2)       # original + one retry
        self.assertEqual(post.call_count, 2)          # refreshed the JWT once
        # Second attempt used the refreshed token.
        second_headers = request.call_args_list[1].kwargs['headers']
        self.assertEqual(second_headers['Authorization'], 'Bearer tok-new')

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    @mock.patch('payouts.providers.nowpayments.base.requests.post')
    def test_persistent_401_raises_after_single_retry(self, post, request):
        post.return_value = _resp(json_data={'token': 'tok'})
        request.return_value = _resp(status=401, content=b'{"message":"nope"}')
        client = _client()
        with self.assertRaises(NowPaymentsError) as ctx:
            client.get_balance()
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(request.call_count, 2)  # exactly one retry, no infinite loop

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_non_2xx_raises_nowpayments_error(self, request):
        request.return_value = _resp(status=500, content=b'{"message":"boom"}')
        client = _client()
        with self.assertRaises(NowPaymentsError) as ctx:
            client.get_status()  # api-key auth, no JWT needed
        self.assertEqual(ctx.exception.status_code, 500)


class PayoutMethodsTest(SimpleTestCase):
    def setUp(self):
        # Pre-seed the JWT cache so method tests don't need to mock /auth.
        self.client_obj = _client()
        self.client_obj._jwt = 'tok-cached'

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_get_status_uses_api_key_not_jwt(self, request):
        request.return_value = _resp(json_data={'message': 'OK'})
        self.assertEqual(self.client_obj.get_status(), {'message': 'OK'})
        headers = request.call_args.kwargs['headers']
        self.assertEqual(headers['x-api-key'], 'dummy-key')
        self.assertNotIn('Authorization', headers)

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_get_balance_uses_jwt(self, request):
        request.return_value = _resp(json_data={'USDTTRC20': {'amount': '5'}})
        out = self.client_obj.get_balance()
        self.assertEqual(out['USDTTRC20']['amount'], '5')
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer tok-cached')

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_validate_address_true_on_2xx(self, request):
        request.return_value = _resp(status=200, json_data={'result': True})
        self.assertTrue(self.client_obj.validate_address('TXyz', 'usdttrc20'))

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_validate_address_raises_on_error(self, request):
        request.return_value = _resp(status=400, content=b'{"message":"bad addr"}')
        with self.assertRaises(NowPaymentsError):
            self.client_obj.validate_address('bad', 'usdttrc20')

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_create_payout_single_entry_and_6dp_and_callback(self, request):
        request.return_value = _resp(json_data={'id': 'batch-1', 'withdrawals': [{'id': 'w-1'}]})
        out = self.client_obj.create_payout(
            'TXaddr', 'usdttrc20', Decimal('12.3456789'), extra_id='req-42')
        self.assertEqual(out['id'], 'batch-1')

        sent = request.call_args.kwargs['json']
        self.assertEqual(list(sent.keys()), ['withdrawals'])
        self.assertEqual(len(sent['withdrawals']), 1)  # EXACTLY one entry
        w = sent['withdrawals'][0]
        self.assertEqual(w['amount'], '12.345678')     # truncated to 6 dp, as string
        self.assertIsInstance(w['amount'], str)
        self.assertEqual(w['address'], 'TXaddr')
        self.assertEqual(w['currency'], 'usdttrc20')
        self.assertEqual(w['extra_id'], 'req-42')
        self.assertEqual(w['ipn_callback_url'], 'https://hook.example.com/ipn')
        # POST /payout carries BOTH api-key and JWT.
        headers = request.call_args.kwargs['headers']
        self.assertEqual(headers['x-api-key'], 'dummy-key')
        self.assertEqual(headers['Authorization'], 'Bearer tok-cached')

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_create_payout_omits_callback_when_unset(self, request):
        request.return_value = _resp(json_data={'id': 'b'})
        client = _client(ipn_callback_url='')
        client._jwt = 'tok-cached'
        client.create_payout('TXaddr', 'usdttrc20', Decimal('1'))
        w = request.call_args.kwargs['json']['withdrawals'][0]
        self.assertNotIn('ipn_callback_url', w)
        self.assertNotIn('extra_id', w)

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_verify_payout_sends_totp_code(self, request):
        request.return_value = _resp(json_data={'status': 'verified'})
        out = self.client_obj.verify_payout('batch-1')
        self.assertEqual(out['status'], 'verified')
        body = request.call_args.kwargs['json']
        self.assertIn('verification_code', body)
        self.assertTrue(body['verification_code'].isdigit())
        self.assertIn('/payout/batch-1/verify', request.call_args.args[1])

    def test_verify_payout_without_totp_secret_raises(self):
        client = _client(totp_secret='')
        client._jwt = 'tok-cached'
        with self.assertRaises(NowPaymentsError):
            client.verify_payout('batch-1')

    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_get_payout_status_parses(self, request):
        request.return_value = _resp(json_data={'id': 'batch-1', 'status': 'finished'})
        out = self.client_obj.get_payout_status('batch-1')
        self.assertEqual(out['status'], 'finished')


class SecretsNotLeakedTest(SimpleTestCase):
    @mock.patch('payouts.providers.nowpayments.base.requests.request')
    def test_error_message_excludes_request_body(self, request):
        # Response body is surfaced (sanitized); the request body (our creds) is not.
        request.return_value = _resp(status=400, content=b'{"message":"server says bad"}')
        client = _client()
        client._jwt = 'tok'
        with self.assertRaises(NowPaymentsError) as ctx:
            client.create_payout('TXaddr', 'usdttrc20', Decimal('1'))
        msg = str(ctx.exception)
        self.assertIn('server says bad', msg)
        self.assertNotIn('TXaddr', msg)
        self.assertNotIn('tok', msg)


@override_settings(
    NOWPAYMENTS_API_KEY='k', NOWPAYMENTS_EMAIL='e@x.com',
    NOWPAYMENTS_PASSWORD='p', NOWPAYMENTS_TOTP_SECRET='JBSWY3DPEHPK3PXP',
    NOWPAYMENTS_BASE_URL=SANDBOX_URL, NOWPAYMENTS_ALLOW_MAINNET=False,
    NOWPAYMENTS_DEFAULT_CURRENCY='usdttrc20',
)
class PreflightCommandTest(SimpleTestCase):
    """Preflight is tested ONLY against a mocked client — never the network."""

    def _run(self):
        from io import StringIO
        out = StringIO()
        call_command('nowpayments_preflight', stdout=out, stderr=out)
        return out.getvalue()

    @mock.patch('payouts.management.commands.nowpayments_preflight.NowPaymentsPayoutClient')
    def test_all_checks_pass(self, client_cls):
        client = client_cls.return_value
        client._get_jwt.return_value = 'x' * 40
        client.get_status.return_value = {'message': 'OK'}
        client.get_balance.return_value = {'USDTTRC20': {'amount': '0'}}
        client.validate_address.return_value = True
        output = self._run()
        self.assertIn('PREFLIGHT PASSED', output)
        self.assertNotIn('FAIL', output)

    @mock.patch('payouts.management.commands.nowpayments_preflight.NowPaymentsPayoutClient')
    def test_balance_failure_fails_preflight(self, client_cls):
        client = client_cls.return_value
        client._get_jwt.return_value = 'x' * 40
        client.get_status.return_value = {'message': 'OK'}
        client.get_balance.side_effect = NowPaymentsError('no custody', status_code=404)
        client.validate_address.return_value = True
        output = self._run()
        self.assertIn('PREFLIGHT FAILED', output)

    @override_settings(NOWPAYMENTS_API_KEY='')
    @mock.patch('payouts.management.commands.nowpayments_preflight.NowPaymentsPayoutClient')
    def test_missing_required_setting_reports_name_only(self, client_cls):
        client = client_cls.return_value
        client._get_jwt.return_value = 'x' * 40
        client.get_status.return_value = {}
        client.get_balance.return_value = {}
        client.validate_address.return_value = True
        output = self._run()
        self.assertIn('NOWPAYMENTS_API_KEY', output)
        self.assertIn('FAIL', output)

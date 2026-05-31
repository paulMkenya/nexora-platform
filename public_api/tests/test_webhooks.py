"""Tests for webhook delivery, retry, and HMAC signature."""
import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from public_api.models import WebhookDelivery, WebhookEndpoint
from public_api.tasks import _sign, deliver_webhook, dispatch_webhook_event


@pytest.mark.django_db
class TestWebhookDelivery:
    def test_sign_produces_sha256_hmac(self):
        secret = 'testsecret'
        payload = b'{"event":"offer.created"}'
        sig = _sign(secret, payload)
        assert sig.startswith('sha256=')
        expected = 'sha256=' + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert sig == expected

    def test_successful_delivery_marks_delivered(self, webhook_endpoint):
        delivery = WebhookDelivery.objects.create(
            endpoint=webhook_endpoint,
            event='offer.created',
            payload={'id': 1, 'title': 'Test'},
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch('public_api.tasks.http_requests.post', return_value=mock_resp) as mock_post:
            deliver_webhook(delivery.pk)

        delivery.refresh_from_db()
        assert delivery.status == WebhookDelivery.STATUS_DELIVERED
        assert delivery.delivered_at is not None
        assert delivery.attempts == 1

        # Verify HMAC header was sent
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1]['headers'] if call_kwargs[1] else call_kwargs.kwargs['headers']
        assert 'X-Nexora-Signature' in headers
        assert headers['X-Nexora-Signature'].startswith('sha256=')

    def test_failed_delivery_increments_attempts(self, webhook_endpoint):
        delivery = WebhookDelivery.objects.create(
            endpoint=webhook_endpoint,
            event='offer.created',
            payload={'id': 1},
        )
        with patch('public_api.tasks.http_requests.post', side_effect=Exception('Connection refused')):
            try:
                deliver_webhook(delivery.pk)
            except Exception:
                pass

        delivery.refresh_from_db()
        assert delivery.attempts == 1
        assert delivery.last_error != ''
        assert delivery.next_retry_at is not None

    def test_max_retries_marks_failed(self, webhook_endpoint):
        delivery = WebhookDelivery.objects.create(
            endpoint=webhook_endpoint,
            event='offer.created',
            payload={'id': 1},
            attempts=2,  # already at max - 1
        )
        with patch('public_api.tasks.http_requests.post', side_effect=Exception('Timeout')):
            try:
                deliver_webhook(delivery.pk)
            except Exception:
                pass

        delivery.refresh_from_db()
        assert delivery.status == WebhookDelivery.STATUS_FAILED

    def test_idempotent_if_already_delivered(self, webhook_endpoint):
        """Already-delivered webhook must not be re-sent."""
        delivery = WebhookDelivery.objects.create(
            endpoint=webhook_endpoint,
            event='offer.created',
            payload={'id': 1},
            status=WebhookDelivery.STATUS_DELIVERED,
            attempts=1,
        )
        with patch('public_api.tasks.http_requests.post') as mock_post:
            deliver_webhook(delivery.pk)
        mock_post.assert_not_called()

    def test_dispatch_creates_delivery_per_endpoint(self, brand, webhook_endpoint):
        """dispatch_webhook_event creates one delivery per active endpoint."""
        with patch('public_api.tasks.deliver_webhook') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_webhook_event(brand.pk, 'offer.created', {'id': 99})

        deliveries = WebhookDelivery.objects.filter(endpoint=webhook_endpoint, event='offer.created')
        assert deliveries.count() == 1

    def test_no_delivery_for_unsubscribed_event(self, brand, webhook_endpoint):
        """Events not in the endpoint's subscription list are not delivered."""
        # webhook_endpoint subscribes to ['offer.created', 'conversion.approved'] but not 'payout.paid'
        initial_count = WebhookDelivery.objects.count()
        with patch('public_api.tasks.deliver_webhook') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_webhook_event(brand.pk, 'payout.paid', {'id': 99})

        assert WebhookDelivery.objects.count() == initial_count

    def test_webhook_endpoint_for_event_filter(self, brand):
        """for_event() returns only active endpoints subscribed to that event."""
        import secrets
        ep1 = WebhookEndpoint.objects.create(
            brand=brand, url='https://a.test', secret=secrets.token_urlsafe(16),
            events=['offer.created'], is_active=True,
        )
        ep2 = WebhookEndpoint.objects.create(
            brand=brand, url='https://b.test', secret=secrets.token_urlsafe(16),
            events=['conversion.approved'], is_active=True,
        )
        ep_inactive = WebhookEndpoint.objects.create(
            brand=brand, url='https://c.test', secret=secrets.token_urlsafe(16),
            events=['offer.created'], is_active=False,
        )
        result = list(WebhookEndpoint.for_event(brand.pk, 'offer.created'))
        assert ep1 in result
        assert ep2 not in result
        assert ep_inactive not in result

    def test_network_admin_can_list_webhooks(self, brand):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        User = get_user_model()
        admin = User.objects.create_superuser(username='wh_admin', password='pass', email='wh@test.com')

        factory = RequestFactory()
        req = factory.get('/api/v1/admin/webhooks')
        req.user = admin
        req.brand = brand

        from public_api.views.webhooks import WebhookEndpointListView
        view = WebhookEndpointListView.as_view()
        resp = view(req)
        assert resp.status_code == 200
        assert isinstance(resp.data, list)

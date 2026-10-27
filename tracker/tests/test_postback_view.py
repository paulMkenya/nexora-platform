import uuid

from django.test import TestCase
from unittest import mock
from django.urls import reverse


class TestPostbackHanlder(TestCase):

    def test_returns_400(self):
        url = reverse('tracker-postback')
        response = self.client.get(url)
        self.assertEqual(400, response.status_code)

    @mock.patch('tracker.views.conversion')
    def test_returns_200(self, mock_conversion):
        url = reverse('tracker-postback')
        response = self.client.get(url, {'click_id': uuid.uuid4().hex, 'goal': 1})
        self.assertEqual(200, response.status_code)
        self.assertTrue(mock_conversion.delay.called)

    @mock.patch('tracker.views.conversion')
    def test_unsubstituted_macro_is_rejected_and_logged(self, mock_conversion):
        from tracker.models import InboundPostbackLog
        url = reverse('tracker-postback')
        response = self.client.get(url, {'click_id': '{rcid}', 'sum': '{payout}'})
        self.assertEqual(400, response.status_code)
        self.assertFalse(mock_conversion.delay.called)
        self.assertEqual(InboundPostbackLog.objects.get().note, 'Unsubstituted macro')

    @mock.patch('tracker.views.conversion')
    def test_txid_is_passed_to_the_task(self, mock_conversion):
        url = reverse('tracker-postback')
        click_id = uuid.uuid4().hex
        self.client.get(url, {'click_id': click_id, 'txid': 'TX-1'})
        self.assertEqual(mock_conversion.delay.call_args[0][0]['txid'], 'TX-1')

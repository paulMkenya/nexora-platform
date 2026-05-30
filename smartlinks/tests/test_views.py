from unittest import mock

from django.test import TestCase
from django.urls import reverse


def _make_cache_data(is_active=True, default_url='http://default.com', rules=None):
    return {
        'id': 1,
        'name': 'Test Smart Link',
        'alias': 'test-link',
        'default_url': default_url,
        'is_active': is_active,
        'rules': rules or [],
    }


class TestSmartLinkView(TestCase):

    def _url(self, alias='test-link'):
        return reverse('smart-link', kwargs={'alias': alias})

    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=None)
    def test_404_when_alias_not_in_cache(self, _mock):
        response = self.client.get(self._url())
        self.assertEqual(404, response.status_code)

    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data(is_active=False))
    def test_404_when_smart_link_inactive(self, _mock):
        response = self.client.get(self._url())
        self.assertEqual(404, response.status_code)

    @mock.patch('smartlinks.views.smart_link_click')
    @mock.patch('smartlinks.views.get_device_type', return_value='desktop')
    @mock.patch('smartlinks.views.get_country', return_value='US')
    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data())
    def test_302_redirect_to_default_url_when_no_rules(self, _cache, _country, _device, _task):
        response = self.client.get(self._url())
        self.assertEqual(302, response.status_code)
        self.assertEqual('http://default.com', response['Location'])

    @mock.patch('smartlinks.views.smart_link_click')
    @mock.patch('smartlinks.views.get_device_type', return_value='mobile')
    @mock.patch('smartlinks.views.get_country', return_value='US')
    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data(
        rules=[{
            'priority': 10,
            'destination_url': 'http://mobile-us.com',
            'countries': 'US',
            'device_type': 'mobile',
            'is_active': True,
        }],
    ))
    def test_302_redirect_to_matching_rule_url(self, _cache, _country, _device, _task):
        response = self.client.get(self._url())
        self.assertEqual(302, response.status_code)
        self.assertEqual('http://mobile-us.com', response['Location'])

    @mock.patch('smartlinks.views.smart_link_click')
    @mock.patch('smartlinks.views.get_device_type', return_value='desktop')
    @mock.patch('smartlinks.views.get_country', return_value='DE')
    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data(
        rules=[{
            'priority': 10,
            'destination_url': 'http://us-only.com',
            'countries': 'US',
            'device_type': 'any',
            'is_active': True,
        }],
    ))
    def test_302_falls_back_to_default_when_no_rule_matches(self, _cache, _country, _device, _task):
        response = self.client.get(self._url())
        self.assertEqual(302, response.status_code)
        self.assertEqual('http://default.com', response['Location'])

    @mock.patch('smartlinks.views.smart_link_click')
    @mock.patch('smartlinks.views.get_device_type', return_value='desktop')
    @mock.patch('smartlinks.views.get_country', return_value='US')
    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data())
    def test_click_task_not_called_without_pid(self, _cache, _country, _device, mock_task):
        self.client.get(self._url())
        mock_task.delay.assert_not_called()

    @mock.patch('smartlinks.views.smart_link_click')
    @mock.patch('smartlinks.views.get_device_type', return_value='desktop')
    @mock.patch('smartlinks.views.get_country', return_value='US')
    @mock.patch('smartlinks.views.SmartLinksCache.get', return_value=_make_cache_data())
    def test_click_task_called_with_pid(self, _cache, _country, _device, mock_task):
        self.client.get(self._url() + '?pid=42')
        mock_task.delay.assert_called_once()
        call_data = mock_task.delay.call_args[0][0]
        self.assertEqual('42', call_data['pid'])
        self.assertEqual('US', call_data['country'])
        self.assertEqual('desktop', call_data['device_type'])
        self.assertEqual('http://default.com', call_data['destination_url'])

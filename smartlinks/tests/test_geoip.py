from unittest import mock

from ext.geoip import country_code


class TestCountryCode:

    def test_empty_ip_returns_empty_string(self):
        assert country_code('') == ''

    def test_returns_empty_when_db_not_found(self):
        with mock.patch('ext.geoip._get_reader', return_value=None):
            assert country_code('8.8.8.8') == ''

    def test_returns_empty_on_reader_exception(self):
        mock_reader = mock.MagicMock()
        mock_reader.country.side_effect = Exception('lookup failed')
        with mock.patch('ext.geoip._get_reader', return_value=mock_reader):
            result = country_code('8.8.8.8')
        assert result == ''

    def test_returns_iso_code_on_success(self):
        mock_response = mock.MagicMock()
        mock_response.country.iso_code = 'US'
        mock_reader = mock.MagicMock()
        mock_reader.country.return_value = mock_response
        with mock.patch('ext.geoip._get_reader', return_value=mock_reader):
            result = country_code('8.8.8.8')
        assert result == 'US'

    def test_returns_empty_when_iso_code_is_none(self):
        mock_response = mock.MagicMock()
        mock_response.country.iso_code = None
        mock_reader = mock.MagicMock()
        mock_reader.country.return_value = mock_response
        with mock.patch('ext.geoip._get_reader', return_value=mock_reader):
            result = country_code('192.168.1.1')
        assert result == ''

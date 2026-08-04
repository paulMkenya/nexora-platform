"""Tests for leadgen/security.py's SSRF guard on affiliate-controlled
postback URLs — Affiliate Inbound API spec Phase 7's security hardening
pass. socket.getaddrinfo is mocked throughout so these are fast, deterministic
unit tests independent of real DNS/network."""
import socket
from unittest.mock import patch

import pytest

from leadgen.security import (
    PostbackURLResolutionError,
    UnsafePostbackURLError,
    validate_postback_url,
)


def _addrinfo(ip):
    """One socket.getaddrinfo()-shaped result tuple for `ip`."""
    return [(2, 1, 6, '', (ip, 0))]


class TestValidatePostbackUrl:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(UnsafePostbackURLError, match='http'):
            validate_postback_url('ftp://example.com/cb')

    def test_rejects_url_with_no_host(self):
        with pytest.raises(UnsafePostbackURLError, match='host'):
            validate_postback_url('https:///cb')

    def test_rejects_unresolvable_host(self):
        """Raises the resolution-specific subclass, which the delivery task
        treats as transient and retries — but it is still an
        UnsafePostbackURLError, so save-time callers catching the parent
        reject it exactly as before."""
        with patch('leadgen.security.socket.getaddrinfo', side_effect=socket.gaierror('mocked NXDOMAIN')):
            with pytest.raises(PostbackURLResolutionError, match='resolved'):
                validate_postback_url('https://this-does-not-exist.example/cb')
        with patch('leadgen.security.socket.getaddrinfo', side_effect=socket.gaierror('mocked NXDOMAIN')):
            with pytest.raises(UnsafePostbackURLError):
                validate_postback_url('https://this-does-not-exist.example/cb')

    def test_private_address_is_not_a_resolution_error(self):
        """The permanent/transient split the delivery task depends on."""
        with patch('leadgen.security.socket.getaddrinfo', return_value=_addrinfo('127.0.0.1')):
            with pytest.raises(UnsafePostbackURLError) as exc_info:
                validate_postback_url('https://internal.example/cb')
        assert not isinstance(exc_info.value, PostbackURLResolutionError)

    @pytest.mark.parametrize('ip,label', [
        ('127.0.0.1', 'loopback'),
        ('10.0.0.5', 'private class A'),
        ('192.168.1.1', 'private class C'),
        ('172.16.0.1', 'private class B'),
        ('169.254.169.254', 'link-local / cloud metadata'),
        ('0.0.0.0', 'unspecified'),
        ('224.0.0.1', 'multicast'),
    ])
    def test_rejects_unsafe_ip(self, ip, label):
        with patch('leadgen.security.socket.getaddrinfo', return_value=_addrinfo(ip)):
            with pytest.raises(UnsafePostbackURLError, match='private or internal'):
                validate_postback_url('https://internal.example/cb')

    def test_allows_public_ip(self):
        with patch('leadgen.security.socket.getaddrinfo', return_value=_addrinfo('93.184.216.34')):
            validate_postback_url('https://public.example/cb')  # must not raise

    def test_rejects_if_any_resolved_address_is_unsafe(self):
        """A hostname that resolves to multiple A/AAAA records is unsafe if
        even one of them is private — an attacker only needs one."""
        with patch('leadgen.security.socket.getaddrinfo',
                    return_value=_addrinfo('93.184.216.34') + _addrinfo('127.0.0.1')):
            with pytest.raises(UnsafePostbackURLError):
                validate_postback_url('https://mixed.example/cb')

"""Guards against SSRF via affiliate-controlled outbound URLs (Affiliate
Inbound API spec Phase 7's security hardening pass). AffiliatePostbackConfig
is the one place in this app where an external, semi-trusted party (an
approved affiliate, not an operator) supplies a URL that our OWN worker then
makes outbound HTTP requests to. Without a check, an affiliate could point
their postback at an internal service (Redis, the Django admin's internal
network, a cloud metadata endpoint) and use the response status/error the
delivery log surfaces back to them as an SSRF oracle.

validate_postback_url() is called from three places, deliberately:
  1. AffiliatePostbackConfig.clean() — covers the Django admin path (its
     ModelForm calls full_clean() automatically).
  2. affiliate_ui.views.postbacks_views — covers the self-service path,
     which uses raw request.POST, not a ModelForm, so needs an explicit call.
  3. leadgen.postback_delivery.deliver_affiliate_postback, immediately
     before the actual request — DNS can be repointed between when a URL is
     saved and when a lead status later fires the postback (DNS rebinding),
     so save-time validation alone isn't enough."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafePostbackURLError(ValueError):
    pass


def _is_unsafe_ip(ip_str):
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def validate_postback_url(url):
    """Raise UnsafePostbackURLError if `url` is not a safe target for the
    server to make an outbound request to."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise UnsafePostbackURLError('Postback URL must start with http:// or https://.')
    host = parsed.hostname
    if not host:
        raise UnsafePostbackURLError('Postback URL must include a host.')
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise UnsafePostbackURLError('Postback URL host could not be resolved.')
    for info in infos:
        ip_str = info[4][0]
        if _is_unsafe_ip(ip_str):
            raise UnsafePostbackURLError(
                'Postback URL resolves to a private or internal address, which is not allowed.')

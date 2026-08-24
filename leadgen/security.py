"""Guards against SSRF via affiliate-controlled outbound URLs (Affiliate
Inbound API spec Phase 7's security hardening pass). AffiliatePostbackConfig
is the one place in this app where an external, semi-trusted party (an
approved affiliate, not an operator) supplies a URL that our OWN worker then
makes outbound HTTP requests to. Without a check, an affiliate could point
their postback at an internal service (Redis, the Django admin's internal
network, a cloud metadata endpoint) and use the response status/error the
delivery log surfaces back to them as an SSRF oracle.

validate_postback_url() is called from four places, deliberately:
  1. AffiliatePostbackConfig.clean() — covers the Django admin path (its
     ModelForm calls full_clean() automatically).
  2. affiliate_ui.views.postbacks_views — covers the self-service path,
     which uses raw request.POST, not a ModelForm, so needs an explicit call.
  3. leadgen.serializers.PostbackConfigSerializer.validate_url — covers the
     API path (POST/PATCH /api/postbacks), which an affiliate's own developer
     can reach with just an API key and no portal session.
  4. leadgen.postback_delivery.deliver_affiliate_postback, immediately
     before the actual request — DNS can be repointed between when a URL is
     saved and when a lead status later fires the postback (DNS rebinding),
     so save-time validation alone isn't enough."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafePostbackURLError(ValueError):
    pass


class PostbackURLResolutionError(UnsafePostbackURLError):
    """DNS gave no answer for the host, so we can't say whether the target is
    safe. Distinct from its parent because the two mean different things to a
    caller: a private-address verdict is about the destination and is
    permanent, while a resolver that didn't answer is a network condition that
    may well answer next time. Save-time callers catch the parent and reject
    both alike (an affiliate saving a URL we can't resolve should be told so);
    delivery retries this one instead of burning the delivery. See
    leadgen.postback_delivery.deliver_affiliate_postback."""


def _is_unsafe_ip(ip_str):
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def public_consumer_ip(value):
    """`value` if it is a PUBLIC, routable IP address; None for anything else.

    THE CONSUMER'S IP IS A CLAIM ABOUT A PERSON, NOT ABOUT A CONNECTION, and
    the two are only the same thing when a browser talks to us directly. On
    the affiliate API the connecting peer is the affiliate's SERVER; behind a
    reverse proxy the connecting peer is the PROXY. Substituting either one
    for the consumer's address does not produce a slightly-worse value, it
    produces a confidently wrong one — and we forward it to the buyer, who
    reads it as fraud evidence.

    What that cost in practice: every affiliate-API lead that did not carry
    its own `ip` was stamped with nginx-proxy-manager's Docker bridge address
    and shipped to the buyer as the consumer IP. Identical on every lead, in
    RFC1918 space, and contradicting a `geo` on the other side of the world.

    So this is deliberately a FILTER, not a fallback: a private, loopback,
    link-local, reserved, multicast or unparseable value yields None, and None
    means the field is simply not sent. Telling a buyer nothing is honest and
    costs a small quality score; telling them 172.18.0.7 came from Warsaw is a
    fraud signal against the affiliate.

    NOT _is_unsafe_ip, deliberately, even though the two overlap heavily.
    That predicate answers the SSRF question — "could a request to this reach
    our own infrastructure" — and this one asks something stricter: "is this a
    routable address that identifies a person on the public internet". The gap
    between them is real. Carrier-grade NAT (100.64.0.0/10) is not an SSRF
    concern and passes _is_unsafe_ip cleanly, yet it identifies nobody and
    tells a buyer nothing. `is_global` is exactly the question being asked, so
    it is the one used; it also folds in the documentation ranges
    (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) that show up in copied
    examples.
    """
    text = str(value or '').strip()
    if not text:
        return None
    try:
        if not ipaddress.ip_address(text).is_global:
            return None
    except ValueError:
        return None
    return text


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
        raise PostbackURLResolutionError('Postback URL host could not be resolved.')
    for info in infos:
        ip_str = info[4][0]
        if _is_unsafe_ip(ip_str):
            raise UnsafePostbackURLError(
                'Postback URL resolves to a private or internal address, which is not allowed.')

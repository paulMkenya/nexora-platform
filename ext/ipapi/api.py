import re
import requests
from typing import NamedTuple, Optional


BASE_URL = "http://ip-api.com/json"
TIMEOUT_SECONDS = 3

_ASN_RE = re.compile(r'^AS(\d+)\b')


class Err(Exception): pass  # noqa
class TimeoutErr(Err): pass  # noqa


class Response(NamedTuple):
    country_code: str
    asn: Optional[int] = None
    isp: str = ''
    mobile: Optional[bool] = None


def parse_asn(value: str) -> Optional[int]:
    """'AS33771 Safaricom Limited' -> 33771; anything else -> None."""
    match = _ASN_RE.match(value or '')
    return int(match.group(1)) if match else None


class API(object):

    def query(self, ip: str) -> Response:
        url = f'{BASE_URL}/{ip}'
        params = {
            'fields': 'status,countryCode,as,isp,mobile',
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        except requests.Timeout:
            raise TimeoutErr()
        except requests.RequestException:
            raise Err()
        # 429 = free-tier rate limit (45 req/min); callers fall back to GeoLite2.
        if resp.status_code != 200:
            raise Err()
        data = resp.json()
        if data.get('status') == 'fail':
            raise Err()
        return Response(
            country_code=(data.get('countryCode', '') or ''),
            asn=parse_asn(data.get('as', '')),
            isp=(data.get('isp', '') or '')[:128],
            mobile=data.get('mobile'),
        )

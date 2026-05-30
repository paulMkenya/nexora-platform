import logging
import os

logger = logging.getLogger(__name__)

_reader = None
_db_path = None


def _get_reader():
    global _reader, _db_path
    if _reader is not None:
        return _reader

    try:
        from django.conf import settings
        path = getattr(settings, 'GEOIP_COUNTRY_DB', '/opt/nexora-platform/data/geoip/GeoLite2-Country.mmdb')
    except Exception:
        path = '/opt/nexora-platform/data/geoip/GeoLite2-Country.mmdb'

    if not os.path.exists(path):
        logger.warning('GeoIP: database not found at %s', path)
        return None

    try:
        import geoip2.database
        _reader = geoip2.database.Reader(path)
        _db_path = path
    except Exception as exc:
        logger.warning('GeoIP: failed to open database: %s', exc)
        return None

    return _reader


def country_code(ip: str) -> str:
    """Return 2-letter ISO country code for the given IP, or '' on any failure."""
    if not ip:
        return ''
    reader = _get_reader()
    if reader is None:
        return ''
    try:
        response = reader.country(ip)
        return response.country.iso_code or ''
    except Exception:
        return ''

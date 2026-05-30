from typing import List, Optional

from smartlinks.models import DEVICE_ANY


def resolve_url(rules: List[dict], country: str, device: str) -> Optional[str]:
    """
    Walk rules (already sorted by priority asc) and return the first matching
    destination_url. Returns None when no rule matches.

    A rule matches when:
    - its country list is empty (wildcard) OR the visitor's country is in the list
    - its device_type is 'any' OR equals the visitor's device type
    """
    country_upper = (country or '').upper()
    for rule in rules:
        if not rule.get('is_active', True):
            continue

        rule_countries = rule.get('countries', '')
        if rule_countries:
            allowed = {c.strip().upper() for c in rule_countries.split(',') if c.strip()}
            if country_upper not in allowed:
                continue

        rule_device = rule.get('device_type', DEVICE_ANY)
        if rule_device != DEVICE_ANY and rule_device != device:
            continue

        return rule['destination_url']

    return None

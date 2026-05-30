from smartlinks.router import resolve_url


def _rule(priority=10, destination_url='http://example.com', countries='', device_type='any', is_active=True):
    return {
        'priority': priority,
        'destination_url': destination_url,
        'countries': countries,
        'device_type': device_type,
        'is_active': is_active,
    }


class TestResolveUrl:

    def test_no_rules_returns_none(self):
        assert resolve_url([], 'US', 'desktop') is None

    def test_wildcard_rule_matches_any_country(self):
        rules = [_rule(destination_url='http://a.com')]
        assert resolve_url(rules, 'DE', 'desktop') == 'http://a.com'

    def test_country_match(self):
        rules = [_rule(destination_url='http://us.com', countries='US')]
        assert resolve_url(rules, 'US', 'desktop') == 'http://us.com'

    def test_country_no_match_returns_none(self):
        rules = [_rule(destination_url='http://us.com', countries='US')]
        assert resolve_url(rules, 'DE', 'desktop') is None

    def test_country_case_insensitive(self):
        rules = [_rule(destination_url='http://us.com', countries='us')]
        assert resolve_url(rules, 'US', 'desktop') == 'http://us.com'

    def test_multi_country_match(self):
        rules = [_rule(destination_url='http://en.com', countries='US,GB,CA')]
        assert resolve_url(rules, 'GB', 'mobile') == 'http://en.com'

    def test_device_match(self):
        rules = [_rule(destination_url='http://mob.com', device_type='mobile')]
        assert resolve_url(rules, 'US', 'mobile') == 'http://mob.com'

    def test_device_no_match_returns_none(self):
        rules = [_rule(destination_url='http://mob.com', device_type='mobile')]
        assert resolve_url(rules, 'US', 'desktop') is None

    def test_both_geo_and_device_match(self):
        rules = [_rule(destination_url='http://us-mob.com', countries='US', device_type='mobile')]
        assert resolve_url(rules, 'US', 'mobile') == 'http://us-mob.com'

    def test_both_geo_and_device_geo_mismatch(self):
        rules = [_rule(destination_url='http://us-mob.com', countries='US', device_type='mobile')]
        assert resolve_url(rules, 'DE', 'mobile') is None

    def test_priority_order_first_wins(self):
        rules = [
            _rule(priority=10, destination_url='http://first.com'),
            _rule(priority=20, destination_url='http://second.com'),
        ]
        assert resolve_url(rules, 'US', 'desktop') == 'http://first.com'

    def test_inactive_rule_is_skipped(self):
        rules = [
            _rule(priority=10, destination_url='http://inactive.com', is_active=False),
            _rule(priority=20, destination_url='http://active.com'),
        ]
        assert resolve_url(rules, 'US', 'desktop') == 'http://active.com'

    def test_first_matching_rule_wins_not_best(self):
        rules = [
            _rule(priority=10, destination_url='http://mobile-us.com', countries='US', device_type='mobile'),
            _rule(priority=20, destination_url='http://any.com'),
        ]
        # Desktop US: first rule fails device check, second matches wildcard
        assert resolve_url(rules, 'US', 'desktop') == 'http://any.com'

    def test_empty_country_in_list_ignored(self):
        rules = [_rule(destination_url='http://a.com', countries='US,,GB')]
        assert resolve_url(rules, 'GB', 'desktop') == 'http://a.com'

    def test_device_any_matches_all_devices(self):
        rules = [_rule(destination_url='http://a.com', device_type='any')]
        for device in ('mobile', 'desktop', 'tablet'):
            assert resolve_url(rules, 'US', device) == 'http://a.com'

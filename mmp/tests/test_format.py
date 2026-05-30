from mmp.format import format_click_url, build_mmp_click_url


def test_format_all_macros():
    tpl = 'https://app.example.com/{app_id}?click={click_id}&aff={affiliate_id}&offer={offer_id}'
    result = format_click_url(tpl, {
        'app_id': 'MYAPP',
        'click_id': 'abc123',
        'affiliate_id': '42',
        'offer_id': '7',
    })
    assert result == 'https://app.example.com/MYAPP?click=abc123&aff=42&offer=7'


def test_format_partial_macros():
    tpl = 'https://app.example.com/{app_id}?click={click_id}'
    result = format_click_url(tpl, {'app_id': 'X', 'click_id': 'Y'})
    assert 'X' in result
    assert 'Y' in result
    assert '{app_id}' not in result
    assert '{click_id}' not in result


def test_format_unknown_macro_left_intact():
    tpl = 'https://example.com?x={unknown_macro}'
    result = format_click_url(tpl, {'click_id': 'abc'})
    assert '{unknown_macro}' in result


def test_build_mmp_click_url_appsflyer():
    tpl = (
        'https://app.appsflyer.com/{app_id}'
        '?pid=nexora&c={offer_id}&clickid={click_id}&af_siteid={affiliate_id}'
    )
    url = build_mmp_click_url(tpl, click_id='click1', app_id='app1', affiliate_id='5', offer_id='10')
    assert 'app1' in url
    assert 'click1' in url
    assert 'af_siteid=5' in url
    assert 'c=10' in url


def test_build_mmp_click_url_adjust():
    tpl = (
        'https://s2s.adjust.com/engagement'
        '?s2s=1&app_token={app_id}&campaign={offer_id}'
        '&adgroup={affiliate_id}&creative={click_id}'
    )
    url = build_mmp_click_url(tpl, click_id='ccc', app_id='tok123', affiliate_id='99', offer_id='3')
    assert 'app_token=tok123' in url
    assert 'creative=ccc' in url
    assert 'adgroup=99' in url


def test_build_mmp_int_offer_id():
    tpl = 'https://example.com?offer={offer_id}'
    url = build_mmp_click_url(tpl, click_id='x', app_id='y', affiliate_id='1', offer_id=5)
    assert 'offer=5' in url


def test_format_empty_template():
    assert format_click_url('', {}) == ''


def test_format_no_macros_in_template():
    tpl = 'https://example.com/static'
    assert format_click_url(tpl, {'click_id': 'abc'}) == tpl

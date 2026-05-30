from ext.device import device_type


MOBILE_UA = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
)
TABLET_UA = (
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
)
DESKTOP_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)
ANDROID_UA = (
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'
)


class TestDeviceType:

    def test_empty_ua_is_desktop(self):
        assert device_type('') == 'desktop'

    def test_iphone_is_mobile(self):
        assert device_type(MOBILE_UA) == 'mobile'

    def test_android_mobile_is_mobile(self):
        assert device_type(ANDROID_UA) == 'mobile'

    def test_ipad_is_tablet(self):
        assert device_type(TABLET_UA) == 'tablet'

    def test_windows_desktop_is_desktop(self):
        assert device_type(DESKTOP_UA) == 'desktop'

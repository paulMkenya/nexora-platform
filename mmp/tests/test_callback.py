import pytest

from mmp.models import MMP, MMPCallback, VENDOR_APPSFLYER


@pytest.mark.django_db
class TestMMPCallbackModel:

    def _mmp(self, vendor=VENDOR_APPSFLYER):
        return MMP.objects.get_or_create(
            vendor=vendor,
            defaults={
                'name': 'Test MMP',
                'click_template': 'https://example.com/{app_id}?click={click_id}',
                'callback_patterns': {'click_id_param': 'clickid', 'event_name_param': 'event_name'},
                'required_macros': ['app_id', 'click_id'],
            },
        )[0]

    def test_create_callback(self):
        mmp = self._mmp()
        cb = MMPCallback.objects.create(
            vendor=mmp.vendor,
            click_id='click001',
            event_name='install',
            raw_data={'clickid': 'click001', 'event_name': 'install'},
        )
        assert cb.id is not None
        assert cb.processed is False

    def test_idempotency_unique_constraint(self):
        mmp = self._mmp()
        MMPCallback.objects.create(
            vendor=mmp.vendor,
            click_id='click002',
            event_name='install',
        )
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            MMPCallback.objects.create(
                vendor=mmp.vendor,
                click_id='click002',
                event_name='install',
            )

    def test_get_or_create_idempotent(self):
        mmp = self._mmp()
        cb1, created1 = MMPCallback.objects.get_or_create(
            click_id='click003',
            event_name='purchase',
            defaults={'vendor': mmp.vendor},
        )
        cb2, created2 = MMPCallback.objects.get_or_create(
            click_id='click003',
            event_name='purchase',
            defaults={'vendor': mmp.vendor},
        )
        assert created1 is True
        assert created2 is False
        assert cb1.id == cb2.id

    def test_different_event_same_click_allowed(self):
        mmp = self._mmp()
        MMPCallback.objects.create(vendor=mmp.vendor, click_id='click004', event_name='install')
        cb2 = MMPCallback.objects.create(vendor=mmp.vendor, click_id='click004', event_name='purchase')
        assert cb2.id is not None

    def test_str_representation(self):
        mmp = self._mmp()
        cb = MMPCallback.objects.create(
            vendor=mmp.vendor, click_id='click005', event_name='install')
        assert 'click005' in str(cb)
        assert 'install' in str(cb)

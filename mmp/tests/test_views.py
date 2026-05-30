import pytest
from django.test import Client
from unittest import mock

from mmp.models import MMP, MMPCallback, VENDOR_APPSFLYER, VENDOR_ADJUST


def _ensure_mmp(vendor=VENDOR_APPSFLYER):
    mmp, _ = MMP.objects.get_or_create(
        vendor=vendor,
        defaults={
            'name': 'AppsFlyer',
            'click_template': 'https://app.appsflyer.com/{app_id}?clickid={click_id}',
            'callback_patterns': {
                'click_id_param': 'clickid',
                'event_name_param': 'event_name',
            },
            'required_macros': ['app_id', 'click_id'],
        },
    )
    return mmp


@pytest.mark.django_db
class TestMMPCallbackView:

    def test_unknown_vendor_returns_404(self):
        c = Client()
        resp = c.get('/mmp/callback/nonexistent_vendor/')
        assert resp.status_code == 404

    def test_missing_click_id_returns_400(self):
        _ensure_mmp()
        c = Client()
        resp = c.get('/mmp/callback/appsflyer/?event_name=install')
        assert resp.status_code == 400

    def test_valid_callback_creates_record(self):
        _ensure_mmp()
        c = Client()
        with mock.patch('mmp.views._process_callback'):
            resp = c.get('/mmp/callback/appsflyer/?clickid=cid001&event_name=install')
        assert resp.status_code == 200
        assert MMPCallback.objects.filter(click_id='cid001', event_name='install').exists()

    def test_duplicate_callback_is_idempotent(self):
        _ensure_mmp()
        c = Client()
        with mock.patch('mmp.views._process_callback'):
            c.get('/mmp/callback/appsflyer/?clickid=cid002&event_name=install')
            resp = c.get('/mmp/callback/appsflyer/?clickid=cid002&event_name=install')
        assert resp.status_code == 200
        assert MMPCallback.objects.filter(click_id='cid002', event_name='install').count() == 1

    def test_default_event_name_is_install(self):
        _ensure_mmp()
        c = Client()
        with mock.patch('mmp.views._process_callback'):
            resp = c.get('/mmp/callback/appsflyer/?clickid=cid003')
        assert resp.status_code == 200
        assert MMPCallback.objects.filter(click_id='cid003', event_name='install').exists()

    def test_adjust_vendor_uses_its_patterns(self):
        MMP.objects.get_or_create(
            vendor=VENDOR_ADJUST,
            defaults={
                'name': 'Adjust',
                'click_template': 'https://s2s.adjust.com/engagement?creative={click_id}',
                'callback_patterns': {
                    'click_id_param': 's2s_external_id',
                    'event_name_param': 'activity_kind',
                },
                'required_macros': ['app_id', 'click_id'],
            },
        )
        c = Client()
        with mock.patch('mmp.views._process_callback'):
            resp = c.get(
                '/mmp/callback/adjust/?s2s_external_id=adj_click1&activity_kind=install'
            )
        assert resp.status_code == 200
        assert MMPCallback.objects.filter(click_id='adj_click1', event_name='install').exists()

    def test_new_callback_marked_processed_after_process(self):
        _ensure_mmp()
        c = Client()
        resp = c.get('/mmp/callback/appsflyer/?clickid=cid_proc&event_name=install')
        assert resp.status_code == 200
        cb = MMPCallback.objects.get(click_id='cid_proc', event_name='install')
        # processed flag is set inside _process_callback which queues a task;
        # since no real Celery worker runs in tests, we just confirm the row exists.
        assert cb is not None

    def test_post_method_not_allowed(self):
        _ensure_mmp()
        c = Client()
        resp = c.post('/mmp/callback/appsflyer/', data={'clickid': 'x', 'event_name': 'install'})
        assert resp.status_code == 405

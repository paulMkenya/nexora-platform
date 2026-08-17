"""Tests for the set_trackbox_api_key command — the verify-before-write path
that applies the credential unblocking TrackBox status sync.

The behaviour worth pinning is what the command REFUSES. TrackBox answers
``200 OK`` to a credential rejection, so "the command ran and nothing errored"
carries no information on this box; the guarantee has to be that a key the box
does not accept never lands in the database, because a stored-but-wrong key
looks exactly like the outage it was meant to fix.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from leadgen.management.commands.set_trackbox_api_key import DOC_PLACEHOLDER_KEY
from leadgen.models import BoxType, LeadBuyer

GOOD_KEY = 'a-real-key-from-traffix-world'


@pytest.fixture
def trackbox_buyer(db, brand):
    box_type = BoxType.objects.create(
        name='TrackBox', slug='trackbox-test',
        connector_class='leadgen.connectors.TrackBoxConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/signup/procform',
        fetch_endpoint_path='/api/pull/customers',
    )
    buyer = LeadBuyer.objects.create(
        brand=brand, box_type=box_type, name='TrackBox - Test', slug='trackbox-traffixworld',
        is_active=True, auto_inject=False, base_url='https://platform.traffixworld.test',
    )
    buyer.set_api_key(DOC_PLACEHOLDER_KEY)
    buyer.set_extra_credentials({'username': 'DanTVSnew', 'password': 'pw'})
    buyer.save(update_fields=['api_key_encrypted', 'extra_credentials_encrypted'])
    return buyer


def _response(payload, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    return mock


@pytest.fixture
def env_key():
    """Set TRACKBOX_API_KEY for one test and always restore it."""
    previous = os.environ.get('TRACKBOX_API_KEY')

    def _set(value):
        os.environ['TRACKBOX_API_KEY'] = value

    yield _set
    if previous is None:
        os.environ.pop('TRACKBOX_API_KEY', None)
    else:
        os.environ['TRACKBOX_API_KEY'] = previous


@pytest.mark.django_db
class TestRefusesBadInput:
    def test_missing_env_var_is_an_error(self, trackbox_buyer, env_key):
        os.environ.pop('TRACKBOX_API_KEY', None)
        with pytest.raises(CommandError, match='TRACKBOX_API_KEY'):
            call_command('set_trackbox_api_key')

    def test_the_documentation_placeholder_is_refused_by_name(self, trackbox_buyer, env_key):
        """The placeholder is what is stored today and why sync 401s. Storing
        it again would look like a fix and change nothing."""
        env_key(DOC_PLACEHOLDER_KEY)
        with pytest.raises(CommandError, match='placeholder'):
            call_command('set_trackbox_api_key')

    def test_unknown_buyer_slug_is_an_error(self, trackbox_buyer, env_key):
        env_key(GOOD_KEY)
        with pytest.raises(CommandError, match='No LeadBuyer'):
            call_command('set_trackbox_api_key', '--slug', 'does-not-exist')

    def test_buyer_without_username_password_cannot_be_verified(self, trackbox_buyer, env_key):
        trackbox_buyer.set_extra_credentials({})
        trackbox_buyer.save(update_fields=['extra_credentials_encrypted'])
        env_key(GOOD_KEY)
        with pytest.raises(CommandError, match='no username/password'):
            call_command('set_trackbox_api_key')


@pytest.mark.django_db
class TestVerifyBeforeWrite:
    def test_a_rejected_key_is_never_stored(self, trackbox_buyer, env_key):
        """The core guarantee. Their rejection arrives as HTTP 200 with
        status:false, which is why this cannot key off the status line."""
        env_key(GOOD_KEY)
        rejection = _response({'status': False, 'code': 401,
                               'message': 'User and password doesnt match'})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=rejection):
            with pytest.raises(CommandError, match='Not storing'):
                call_command('set_trackbox_api_key')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == DOC_PLACEHOLDER_KEY  # unchanged

    def test_an_accepted_key_is_stored(self, trackbox_buyer, env_key):
        env_key(GOOD_KEY)
        success = _response({'data': [], 'meta': {'page': 1}})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=success):
            call_command('set_trackbox_api_key')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == GOOD_KEY

    def test_a_successful_pull_has_no_status_key_and_must_not_read_as_failure(
            self, trackbox_buyer, env_key):
        """Their good pull body carries data/meta and NO `status` key. Testing
        for a truthy `status` instead of an absent one would treat every
        successful pull as an outage — see TrackBoxConnector._is_soft_error."""
        env_key(GOOD_KEY)
        success = _response({'data': [{'id': 1}], 'meta': {}})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=success):
            call_command('set_trackbox_api_key')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == GOOD_KEY

    def test_check_mode_never_writes_even_on_success(self, trackbox_buyer, env_key):
        env_key(GOOD_KEY)
        success = _response({'data': [], 'meta': {}})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=success):
            call_command('set_trackbox_api_key', '--check')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == DOC_PLACEHOLDER_KEY

    def test_force_stores_despite_rejection(self, trackbox_buyer, env_key):
        env_key(GOOD_KEY)
        rejection = _response({'status': False, 'code': 401, 'message': 'nope'})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=rejection):
            call_command('set_trackbox_api_key', '--force')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == GOOD_KEY

    def test_an_unreachable_box_does_not_store(self, trackbox_buyer, env_key):
        import requests as requests_module

        env_key(GOOD_KEY)
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   side_effect=requests_module.ConnectionError('boom')):
            with pytest.raises(CommandError, match='Not storing'):
                call_command('set_trackbox_api_key')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_api_key() == DOC_PLACEHOLDER_KEY

    def test_the_username_password_are_left_alone(self, trackbox_buyer, env_key):
        """Only the key changes — the working injection path must not be
        disturbed by a credential rotation."""
        env_key(GOOD_KEY)
        success = _response({'data': [], 'meta': {}})
        with patch('leadgen.management.commands.set_trackbox_api_key.requests.post',
                   return_value=success):
            call_command('set_trackbox_api_key')

        trackbox_buyer.refresh_from_db()
        assert trackbox_buyer.get_extra_credentials() == {'username': 'DanTVSnew', 'password': 'pw'}

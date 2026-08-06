"""OFF must mean genuinely inert, not merely hidden.

Each of Paul's four conditions gets its own test, because "the feature is off"
is only as true as its weakest path: a flag that hides the UI but still lets a
management command mint a token has not disabled anything.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from sso import config
from sso.service import issue_token

User = get_user_model()


@pytest.fixture(autouse=True)
def _feature_off(settings):
    """Explicitly off. The production default is also off (asserted below);
    pinning it here keeps these tests honest if the default ever moves."""
    settings.SSO_AUTOLOGIN_ENABLED = False


@pytest.fixture
def user(db):
    return User.objects.create_user(username='sso_off', password='pass')


@pytest.mark.django_db
class TestFeatureOff:
    def test_default_is_off_without_any_env_var(self, settings):
        """The default lives in code. An absent env var means off."""
        del settings.SSO_AUTOLOGIN_ENABLED
        assert config.is_enabled() is False

    def test_endpoint_returns_404(self):
        """Never 403 — that would confirm the feature exists to a prober."""
        assert Client().get('/sso/autologin/?token=whatever').status_code == 404

    def test_no_code_path_can_mint_a_token(self, user):
        """Including management commands, admin and test helpers — they all go
        through issue_token, which raises."""
        with pytest.raises(config.AutologinDisabled):
            issue_token(user)

    def test_middleware_does_not_attach_the_flag(self, user):
        """Not set to False — absent entirely, so nothing downstream can branch
        on a flag that exists only because the code is loaded."""
        from django.test import RequestFactory

        from sso.middleware import AutologinSessionMiddleware

        request = RequestFactory().get('/')
        request.session = {}
        AutologinSessionMiddleware(lambda r: None)(request)
        assert not hasattr(request, 'is_autologin_session')

    def test_absent_from_the_generated_integrator_doc(self, user):
        from django.test import RequestFactory

        from leadgen.api_doc import build_doc_context

        request = RequestFactory().get('/partner/api-docs/')
        request.user = user
        blob = str(build_doc_context(request, user)).lower()
        assert 'autologin' not in blob
        assert '/sso/' not in blob

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from user_profile.models import Profile, User
from user_profile.permissions import IsAdvertiser


class IsAdvertiserPermissionTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = IsAdvertiser()

    def _make_user(self, username, role):
        user = User.objects.create_user(username=username, password='pass')
        user.profile.role = role
        user.profile.save()
        return user

    def _request_for(self, user=None):
        request = self.factory.get('/')
        request.user = user
        return request

    def test_unauthenticated_denied(self):
        from django.contrib.auth.models import AnonymousUser
        request = self._request_for(AnonymousUser())
        self.assertFalse(self.permission.has_permission(request, None))

    def test_affiliate_denied(self):
        user = self._make_user('aff', Profile.Role.AFFILIATE)
        self.assertFalse(self.permission.has_permission(self._request_for(user), None))

    def test_advertiser_allowed(self):
        user = self._make_user('adv', Profile.Role.ADVERTISER)
        self.assertTrue(self.permission.has_permission(self._request_for(user), None))

    def test_affiliate_manager_denied(self):
        user = self._make_user('mgr', Profile.Role.AFFILIATE_MANAGER)
        self.assertFalse(self.permission.has_permission(self._request_for(user), None))

    def test_network_admin_denied(self):
        user = self._make_user('nadm', Profile.Role.NETWORK_ADMIN)
        self.assertFalse(self.permission.has_permission(self._request_for(user), None))

    def test_none_user_denied(self):
        request = self._request_for(None)
        self.assertFalse(self.permission.has_permission(request, None))

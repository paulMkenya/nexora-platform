from django.test import TestCase

from user_profile.models import Profile, User


class ProfileRoleTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='roleuser', password='pass')
        self.profile = self.user.profile  # auto-created by signal

    def test_default_role_is_affiliate(self):
        self.assertEqual(self.profile.role, Profile.Role.AFFILIATE)

    def test_all_role_choices_present(self):
        choice_values = [value for value, _ in Profile.Role.choices]
        self.assertEqual(
            sorted(choice_values),
            sorted(['AFFILIATE', 'ADVERTISER', 'AFFILIATE_MANAGER', 'NETWORK_ADMIN']),
        )

    def test_set_advertiser_role(self):
        self.profile.role = Profile.Role.ADVERTISER
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, Profile.Role.ADVERTISER)

    def test_set_affiliate_manager_role(self):
        self.profile.role = Profile.Role.AFFILIATE_MANAGER
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, Profile.Role.AFFILIATE_MANAGER)

    def test_set_network_admin_role(self):
        self.profile.role = Profile.Role.NETWORK_ADMIN
        self.profile.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, Profile.Role.NETWORK_ADMIN)

    def test_role_persists_across_user_save(self):
        self.profile.role = Profile.Role.ADVERTISER
        self.profile.save()
        self.user.first_name = 'Test'
        self.user.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, Profile.Role.ADVERTISER)

"""
Tests for /advertiser/conversions/ — list, bulk actions, CSV export.

Security invariant: a bulk action may only touch conversions whose
offer.advertiser matches the authenticated user's advertiser record.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tracker.models import (
    APPROVED_STATUS, HOLD_STATUS, PENDING_STATUS, REJECTED_STATUS, Conversion,
)
from user_profile.models import Profile, User

from .factories import (
    make_advertiser_user, make_click, make_conversion, make_offer,
)

CACHES_DUMMY = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}
POSTBACK_PATH = 'postback.tasks.send_postback.send_postback.delay'


# ── helpers ────────────────────────────────────────────────────────────────

def url(name, **kwargs):
    return reverse(f'advertiser_ui:{name}', kwargs=kwargs)


@override_settings(CACHES=CACHES_DUMMY)
class ConversionsListTestCase(TestCase):
    def setUp(self):
        self.user, self.adv = make_advertiser_user('cvlist')
        self.offer = make_offer(self.adv, 'List Offer')
        make_conversion(self.offer, status=APPROVED_STATUS, payout=Decimal('10.00'), n=3)
        make_conversion(self.offer, status=REJECTED_STATUS, payout=Decimal('5.00'),  n=2)
        self.client.force_login(self.user)

    def test_page_returns_200(self):
        r = self.client.get('/advertiser/conversions/')
        self.assertEqual(r.status_code, 200)

    def test_template_used(self):
        r = self.client.get('/advertiser/conversions/')
        self.assertTemplateUsed(r, 'advertiser_ui/conversions.html')

    def test_default_date_range_is_last_7_days(self):
        r = self.client.get('/advertiser/conversions/')
        f = r.context['filters']
        self.assertEqual(f['date_from'], (date.today() - timedelta(days=7)).isoformat())
        self.assertEqual(f['date_to'],   date.today().isoformat())

    def test_all_own_conversions_visible_by_default(self):
        r = self.client.get('/advertiser/conversions/')
        self.assertEqual(r.context['page_obj'].paginator.count, 5)

    def test_filter_by_status_approved(self):
        r = self.client.get('/advertiser/conversions/?status=approved')
        self.assertEqual(r.context['page_obj'].paginator.count, 3)

    def test_filter_by_status_rejected(self):
        r = self.client.get('/advertiser/conversions/?status=rejected')
        self.assertEqual(r.context['page_obj'].paginator.count, 2)

    def test_filter_by_offer(self):
        other_offer = make_offer(self.adv, 'Other Offer')
        make_conversion(other_offer, n=1)
        r = self.client.get(f'/advertiser/conversions/?offer_id={self.offer.pk}')
        self.assertEqual(r.context['page_obj'].paginator.count, 5)

    def test_filter_by_sub1(self):
        c = Conversion.objects.filter(offer=self.offer).first()
        c.sub1 = 'tracksub123'
        c.save()
        r = self.client.get('/advertiser/conversions/?sub1=tracksub')
        self.assertEqual(r.context['page_obj'].paginator.count, 1)

    def test_date_range_excludes_old_conversions(self):
        # Push one conversion into the past beyond default 7-day window
        old = Conversion.objects.filter(offer=self.offer).last()
        Conversion.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        r = self.client.get('/advertiser/conversions/')
        self.assertEqual(r.context['page_obj'].paginator.count, 4)

    def test_other_advertiser_conversions_not_visible(self):
        _, adv2 = make_advertiser_user('cvlist2')
        offer2  = make_offer(adv2, 'Foreign Offer')
        make_conversion(offer2, n=10)
        r = self.client.get('/advertiser/conversions/')
        self.assertEqual(r.context['page_obj'].paginator.count, 5)

    def test_unauthenticated_redirected(self):
        self.client.logout()
        r = self.client.get('/advertiser/conversions/')
        self.assertRedirects(r, '/login/?next=/advertiser/conversions/',
                             fetch_redirect_response=False)

    def test_non_advertiser_gets_403(self):
        u = User.objects.create_user(username='aff_cv', password='pass')
        u.profile.role = Profile.Role.AFFILIATE
        u.profile.save()
        self.client.force_login(u)
        self.assertEqual(self.client.get('/advertiser/conversions/').status_code, 403)


@override_settings(CACHES=CACHES_DUMMY)
class BulkActionSecurityTestCase(TestCase):
    """
    Core security invariant: bulk actions must ONLY update conversions
    belonging to the authenticated advertiser.
    """

    def setUp(self):
        self.user1, self.adv1 = make_advertiser_user('bulkadv1')
        self.user2, self.adv2 = make_advertiser_user('bulkadv2')
        # A separate affiliate user so conversions have affiliate_id set
        # (required by send_postback; needed to verify postback task fires)
        self.affiliate = User.objects.create_user(username='aff_bulk', password='pass')

        self.offer1 = make_offer(self.adv1, 'Adv1 Offer')
        self.offer2 = make_offer(self.adv2, 'Adv2 Offer')

        make_conversion(self.offer1, status=PENDING_STATUS, n=3, affiliate=self.affiliate)
        make_conversion(self.offer2, status=PENDING_STATUS, n=2, affiliate=self.affiliate)

        self.adv1_ids = list(
            Conversion.objects.filter(offer=self.offer1).values_list('pk', flat=True)
        )
        self.adv2_ids = list(
            Conversion.objects.filter(offer=self.offer2).values_list('pk', flat=True)
        )

    def _post_bulk(self, ids, action='approve', reason=''):
        return self.client.post(
            '/advertiser/conversions/bulk/',
            {'ids': [str(i) for i in ids], 'action': action, 'reason': reason},
        )

    # ── own rows are updated ───────────────────────────────────────────────

    @patch(POSTBACK_PATH)
    def test_bulk_approve_own_conversions(self, mock_delay):
        self.client.force_login(self.user1)
        r = self._post_bulk(self.adv1_ids, action='approve')
        self.assertRedirects(r, '/advertiser/conversions/', fetch_redirect_response=False)
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer1, status=APPROVED_STATUS).count(), 3
        )

    @patch(POSTBACK_PATH)
    def test_bulk_reject_own_conversions(self, mock_delay):
        self.client.force_login(self.user1)
        self._post_bulk(self.adv1_ids, action='reject', reason='Fraud')
        convs = Conversion.objects.filter(offer=self.offer1)
        self.assertTrue(all(c.status == REJECTED_STATUS for c in convs))
        self.assertTrue(all(c.comment == 'Fraud' for c in convs))

    @patch(POSTBACK_PATH)
    def test_bulk_hold_own_conversions(self, mock_delay):
        self.client.force_login(self.user1)
        self._post_bulk(self.adv1_ids, action='hold')
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer1, status=HOLD_STATUS).count(), 3
        )

    # ── foreign rows are NOT touched ─────────────────────────────────────

    @patch(POSTBACK_PATH)
    def test_bulk_approve_does_not_touch_foreign_conversions(self, mock_delay):
        """Passing another advertiser's IDs must leave those rows unchanged."""
        self.client.force_login(self.user1)
        self._post_bulk(self.adv2_ids, action='approve')
        # adv2's conversions must remain pending
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer2, status=PENDING_STATUS).count(), 2
        )

    @patch(POSTBACK_PATH)
    def test_bulk_with_mixed_ids_only_updates_own(self, mock_delay):
        """Mix of own + foreign IDs: only own rows change."""
        self.client.force_login(self.user1)
        mixed = self.adv1_ids + self.adv2_ids
        self._post_bulk(mixed, action='approve')
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer1, status=APPROVED_STATUS).count(), 3
        )
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer2, status=PENDING_STATUS).count(), 2
        )

    # ── postback task is queued ────────────────────────────────────────────

    @patch(POSTBACK_PATH)
    def test_postback_task_queued_once_per_updated_conversion(self, mock_delay):
        self.client.force_login(self.user1)
        self._post_bulk(self.adv1_ids, action='approve')
        # One postback.delay call per conversion that has an affiliate+offer
        self.assertEqual(mock_delay.call_count, 3)

    @patch(POSTBACK_PATH)
    def test_postback_not_queued_for_foreign_ids(self, mock_delay):
        """Passing foreign IDs must not trigger any postback tasks."""
        self.client.force_login(self.user1)
        self._post_bulk(self.adv2_ids, action='approve')
        mock_delay.assert_not_called()

    # ── edge cases ─────────────────────────────────────────────────────────

    @patch(POSTBACK_PATH)
    def test_empty_ids_redirects_without_update(self, mock_delay):
        self.client.force_login(self.user1)
        r = self.client.post('/advertiser/conversions/bulk/', {'action': 'approve'})
        self.assertEqual(r.status_code, 302)
        mock_delay.assert_not_called()

    @patch(POSTBACK_PATH)
    def test_malformed_uuid_ids_are_silently_dropped(self, mock_delay):
        self.client.force_login(self.user1)
        r = self._post_bulk(['not-a-uuid', 'also-bad'], action='approve')
        self.assertEqual(r.status_code, 302)
        mock_delay.assert_not_called()

    def test_invalid_action_does_not_update(self):
        self.client.force_login(self.user1)
        r = self.client.post('/advertiser/conversions/bulk/',
                             {'ids': [str(i) for i in self.adv1_ids], 'action': 'delete'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Conversion.objects.filter(offer=self.offer1, status=PENDING_STATUS).count(), 3
        )

    def test_unauthenticated_bulk_redirected(self):
        r = self.client.post('/advertiser/conversions/bulk/',
                             {'ids': [str(self.adv1_ids[0])], 'action': 'approve'})
        self.assertRedirects(r, '/login/?next=/advertiser/conversions/bulk/',
                             fetch_redirect_response=False)


@override_settings(CACHES=CACHES_DUMMY)
class CsvExportTestCase(TestCase):
    def setUp(self):
        self.user1, self.adv1 = make_advertiser_user('csvadv1')
        self.user2, self.adv2 = make_advertiser_user('csvadv2')

        self.offer1 = make_offer(self.adv1, 'Export Offer')
        self.offer2 = make_offer(self.adv2, 'Foreign Offer')

        make_conversion(self.offer1, status=APPROVED_STATUS, payout=Decimal('20.00'), n=4)
        make_conversion(self.offer2, status=APPROVED_STATUS, payout=Decimal('99.00'), n=2)

        self.client.force_login(self.user1)

    def _get_csv(self, qs=''):
        return self.client.get(f'/advertiser/conversions/export/{qs}')

    def test_returns_200(self):
        self.assertEqual(self._get_csv().status_code, 200)

    def test_content_type_is_csv(self):
        r = self._get_csv()
        self.assertIn('text/csv', r['Content-Type'])

    def test_content_disposition_attachment(self):
        r = self._get_csv()
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('conversions.csv', r['Content-Disposition'])

    def test_csv_contains_own_conversions(self):
        r = self._get_csv()
        content = r.content.decode()
        reader = list(csv.reader(io.StringIO(content)))
        # header + 4 data rows
        self.assertEqual(len(reader), 5)

    def test_csv_does_not_contain_foreign_offer(self):
        r = self._get_csv()
        self.assertNotIn('Foreign Offer', r.content.decode())

    def test_csv_header_row_present(self):
        r = self._get_csv()
        first_line = r.content.decode().splitlines()[0]
        self.assertIn('ID', first_line)
        self.assertIn('Status', first_line)
        self.assertIn('Payout', first_line)

    def test_csv_status_filter_respected(self):
        make_conversion(self.offer1, status=REJECTED_STATUS, n=2)
        r = self._get_csv('?status=approved')
        reader = list(csv.reader(io.StringIO(r.content.decode())))
        # header + 4 approved rows only
        self.assertEqual(len(reader), 5)

    def test_unauthenticated_export_redirected(self):
        self.client.logout()
        r = self._get_csv()
        self.assertEqual(r.status_code, 302)

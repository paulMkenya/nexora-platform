"""Idempotent provisioning of Cloudtrade's own affiliate-referral offer.

Why this exists: Cloudtrade's sites (cloudtrade.pro, pos.cloudtrade.pro,
demo.cloudtrade.pro) are wired to send ``/postback?click_id=…&goal=1&
status=pending&sum=0`` for every free-trial sign-up and demo lead, but nothing
on the Nexora side existed to receive them. This creates the advertiser, the
"Qualified lead" goal, the offer with its two extra landings, the single $10
payout and the advertiser's HMAC postback key — and nothing else. Sale /
recurring-commission payouts are deliberately NOT created: billing is not live
on the POS, so there is no sale event to pay on.

SAFETY
------
* Idempotent by natural key (brand + advertiser email, offer title, landing
  name, payout goal_value): re-running updates in place, creates no duplicates.
* The HMAC secret is NEVER printed. It is written only to ``--secret-file``
  (created mode 0600) when given; otherwise only a short fingerprint is shown.
  A re-run never rotates the key unless ``--rotate-key`` is passed, so a
  working integration is not broken by an accidental second run.
* Payout countries == offer countries == Kenya. ``tracker.tasks.conversion``
  matches a payout on the CLICK's geo-IP country, so a click from anywhere
  else converts as REJECTED "Payout not found" — that is the intended targeting.
"""
import hashlib
import os

from countries_plus.models import Country
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from advertiser_ui.services import get_or_create_postback_key, regenerate_postback_key
from brands.models import Brand
from offer.models import (
    ACTIVE_STATUS, ALLOW_LIST, CPA, FIXED_PAYOUT,
    Advertiser, Currency, Goal, Landing, Offer, Payout,
)

BRAND_SLUG = 'nexora'

ADVERTISER_EMAIL = 'support@cloudtrade.pro'
ADVERTISER = dict(
    company='Cloudtrade Centralised Systems Ltd',
    contact_person='Paul Mugendi',
    site='https://cloudtrade.pro',
    country='KE',
)

GOAL_NAME = 'Qualified lead'
GOAL_VALUE = '1'
COUNTRIES = ['KE']

OFFER_TITLE = 'Cloudtrade ERP & POS – Free trial & demo leads'
OFFER = dict(
    tracking_link='https://cloudtrade.pro/?click_id={click_id}&pid={pid}',
    preview_link='https://cloudtrade.pro/',
    revenue_model=CPA,
    country_mode=ALLOW_LIST,
    status=ACTIVE_STATUS,
    description=(
        '$10 for every qualified lead who signs up for a free trial of '
        'Cloudtrade POS or books a live demo of Cloudtrade ERP.'
    ),
)
LANDINGS = [
    ('Live demo', 'https://demo.cloudtrade.pro/?click_id={click_id}&pid={pid}',
     'https://demo.cloudtrade.pro/'),
    ('Trial sign-up',
     'https://pos.cloudtrade.pro/business/register?click_id={click_id}&pid={pid}',
     'https://pos.cloudtrade.pro/business/register'),
]
PAYOUT_AMOUNT = '10.00'
REVENUE_AMOUNT = '10.00'
CURRENCY = 'USD'


def _fingerprint(secret):
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


class Command(BaseCommand):
    help = "Idempotently provision Cloudtrade's affiliate-referral offer, payout and postback key."

    def add_arguments(self, parser):
        parser.add_argument(
            '--secret-file',
            help='Write the advertiser HMAC secret here (mode 0600). It is never printed.')
        parser.add_argument(
            '--rotate-key', action='store_true',
            help='Regenerate the HMAC secret. Off by default: rotating breaks '
                 'NEXORA_POSTBACK_SECRET on the Cloudtrade box until it is updated.')

    def handle(self, *args, **options):
        brand = Brand.objects.filter(slug=BRAND_SLUG).first()
        if brand is None:
            raise CommandError(f'Brand "{BRAND_SLUG}" not found.')

        countries = list(Country.objects.filter(iso__in=COUNTRIES))
        if len(countries) != len(COUNTRIES):
            raise CommandError(f'Missing countries_plus rows for {COUNTRIES}.')
        try:
            currency = Currency.objects.get(code=CURRENCY)
        except Currency.DoesNotExist:
            raise CommandError(f'Currency {CURRENCY} not found.')

        with transaction.atomic():
            advertiser, adv_created = Advertiser.objects.update_or_create(
                brand=brand, email=ADVERTISER_EMAIL,
                defaults=dict(
                    ADVERTISER,
                    # Both are required by offers_for_affiliate's advertiser
                    # gate — an unverified advertiser's offers are invisible.
                    advertiser_status=Advertiser.AdvertiserStatus.APPROVED,
                    email_verified=True,
                    is_archived=False,
                ),
            )

            goal = Goal.objects.filter(name__iexact=GOAL_NAME).first()
            goal_created = goal is None
            if goal_created:
                goal = Goal.objects.create(name=GOAL_NAME)

            offer, offer_created = Offer.objects.update_or_create(
                brand=brand, title=OFFER_TITLE,
                defaults=dict(OFFER, advertiser=advertiser),
            )
            offer.countries.set(countries)

            for name, url, preview in LANDINGS:
                Landing.objects.update_or_create(
                    offer=offer, name=name,
                    defaults=dict(url=url, preview_url=preview),
                )

            payout, payout_created = Payout.objects.update_or_create(
                offer=offer, goal_value=GOAL_VALUE,
                defaults=dict(
                    goal=goal,
                    payout=PAYOUT_AMOUNT,
                    revenue=REVENUE_AMOUNT,
                    currency=currency,
                    type=FIXED_PAYOUT,
                ),
            )
            payout.countries.set(countries)

            if options['rotate_key']:
                key, key_note = regenerate_postback_key(advertiser), 'rotated'
            else:
                key, key_created = get_or_create_postback_key(advertiser)
                key_note = 'created' if key_created else 'existing (pass --rotate-key to regenerate)'

        # /click reads the offer from Redis, refreshed by a Beat tick; refresh
        # now so the click link works immediately rather than after the tick.
        from offer.tasks.cache_offers import cache_offers
        cache_offers()

        if options['secret_file']:
            fd = os.open(options['secret_file'], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as fh:
                fh.write(key.secret + '\n')

        def state(created):
            return 'created' if created else 'updated'

        w = self.stdout.write
        w(self.style.SUCCESS('Cloudtrade offer seed complete.'))
        w(f'  advertiser : id={advertiser.pk} "{advertiser.company}" {state(adv_created)} [APPROVED, verified]')
        w(f'  goal       : id={goal.pk} "{goal.name}" {"created" if goal_created else "reused"}')
        w(f'  offer      : id={offer.pk} {state(offer_created)} [{offer.status}, {offer.targeting_display()}]')
        w(f'  landings   : {", ".join(n for n, _, _ in LANDINGS)}')
        w(f'  payout     : id={payout.pk} {state(payout_created)} goal_value={GOAL_VALUE} '
          f'{PAYOUT_AMOUNT} {CURRENCY} (revenue {REVENUE_AMOUNT})')
        w(f'  hmac key   : {key_note}, fingerprint {_fingerprint(key.secret)}'
          + (f', written to {options["secret_file"]}' if options['secret_file'] else ''))

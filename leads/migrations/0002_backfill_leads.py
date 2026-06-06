"""Backfill a Lead for every existing affiliate and advertiser.

Idempotent (get_or_create on the entity), so it is safe to re-run. Stages are
derived from each entity's current state, mirroring the live auto-advance rules:

    verified + approved + activity  → ACTIVATED
    verified + approved             → APPROVED
    verified                        → VERIFIED
    otherwise                       → NEW

Activity = an affiliate with any click, or an advertiser with any offer.
Backfilled ACTIVATED leads get ``last_activity_at`` stamped to the migration
time so the dormancy task has a sane baseline.
"""
from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Lead = apps.get_model('leads', 'Lead')
    Profile = apps.get_model('user_profile', 'Profile')
    Advertiser = apps.get_model('offer', 'Advertiser')
    Click = apps.get_model('tracker', 'Click')
    Offer = apps.get_model('offer', 'Offer')

    now = timezone.now()

    # ---- Affiliates ----
    affiliates = Profile.objects.filter(role='AFFILIATE').select_related('user')
    for profile in affiliates:
        user = profile.user
        verified = profile.email_verified
        approved = profile.affiliate_status == 'APPROVED'
        has_activity = bool(
            user and Click.objects.filter(affiliate_id=user.id).exists()
        )
        if verified and approved and has_activity:
            stage = 'ACTIVATED'
        elif verified and approved:
            stage = 'APPROVED'
        elif verified:
            stage = 'VERIFIED'
        else:
            stage = 'NEW'

        name = ' '.join(
            p for p in [getattr(user, 'first_name', ''), getattr(user, 'last_name', '')] if p
        ).strip() or (user.username if user else '')
        Lead.objects.get_or_create(
            profile=profile,
            defaults={
                'lead_type': 'AFFILIATE',
                'brand_id': profile.brand_id,
                'email': (user.email if user else '') or '',
                'name': name,
                'country': profile.country or '',
                'source': 'backfill',
                'pipeline_stage': stage,
                'last_activity_at': now if stage == 'ACTIVATED' else None,
            },
        )

    # ---- Advertisers ----
    for adv in Advertiser.objects.select_related('user').all():
        verified = adv.email_verified
        approved = adv.advertiser_status == 'APPROVED'
        has_activity = Offer.objects.filter(advertiser_id=adv.id).exists()
        if verified and approved and has_activity:
            stage = 'ACTIVATED'
        elif verified and approved:
            stage = 'APPROVED'
        elif verified:
            stage = 'VERIFIED'
        else:
            stage = 'NEW'

        name = (getattr(adv.user, 'first_name', '') if adv.user else '') \
            or adv.contact_person or adv.company
        email = adv.email or (adv.user.email if adv.user else '') or ''
        Lead.objects.get_or_create(
            advertiser=adv,
            defaults={
                'lead_type': 'ADVERTISER',
                'brand_id': adv.brand_id,
                'email': email,
                'name': name,
                'country': adv.country or '',
                'source': 'backfill',
                'pipeline_stage': stage,
                'last_activity_at': now if stage == 'ACTIVATED' else None,
            },
        )


def noop(apps, schema_editor):
    # Reverse: drop backfilled leads only.
    Lead = apps.get_model('leads', 'Lead')
    Lead.objects.filter(source='backfill').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0001_initial'),
        ('tracker', '0016_click_conversion_brand'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]

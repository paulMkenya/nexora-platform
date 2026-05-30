from django.db import migrations

VENDORS = [
    {
        'name': 'AppsFlyer',
        'vendor': 'appsflyer',
        'click_template': (
            'https://app.appsflyer.com/{app_id}'
            '?pid=nexora&c={offer_id}&clickid={click_id}&af_siteid={affiliate_id}'
        ),
        'callback_patterns': {
            'click_id_param': 'clickid',
            'event_name_param': 'event_name',
        },
        'required_macros': ['app_id', 'click_id', 'affiliate_id', 'offer_id'],
    },
    {
        'name': 'Adjust',
        'vendor': 'adjust',
        'click_template': (
            'https://s2s.adjust.com/engagement'
            '?s2s=1&app_token={app_id}&campaign={offer_id}'
            '&adgroup={affiliate_id}&creative={click_id}'
        ),
        'callback_patterns': {
            'click_id_param': 's2s_external_id',
            'event_name_param': 'activity_kind',
        },
        'required_macros': ['app_id', 'click_id', 'affiliate_id', 'offer_id'],
    },
    {
        'name': 'Branch',
        'vendor': 'branch',
        'click_template': (
            'https://bnc.lt/{app_id}'
            '?%24click_id={click_id}&~campaign={offer_id}&~affiliate_id={affiliate_id}'
        ),
        'callback_patterns': {
            'click_id_param': 'click_id',
            'event_name_param': 'event',
        },
        'required_macros': ['app_id', 'click_id', 'affiliate_id', 'offer_id'],
    },
    {
        'name': 'Singular',
        'vendor': 'singular',
        'click_template': (
            'https://s.singular.net/{app_id}'
            '?cl={click_id}&aff_id={affiliate_id}&camp={offer_id}'
        ),
        'callback_patterns': {
            'click_id_param': 'cl',
            'event_name_param': 'event_name',
        },
        'required_macros': ['app_id', 'click_id', 'affiliate_id', 'offer_id'],
    },
    {
        'name': 'Kochava',
        'vendor': 'kochava',
        'click_template': (
            'https://control.kochava.com/track/click'
            '?click_id={click_id}&campaign_id={offer_id}&network_id={affiliate_id}'
            '&site_id={app_id}'
        ),
        'callback_patterns': {
            'click_id_param': 'click_id',
            'event_name_param': 'event_name',
        },
        'required_macros': ['app_id', 'click_id', 'affiliate_id', 'offer_id'],
    },
]


def seed_vendors(apps, schema_editor):
    MMP = apps.get_model('mmp', 'MMP')
    for v in VENDORS:
        MMP.objects.get_or_create(vendor=v['vendor'], defaults={
            'name': v['name'],
            'click_template': v['click_template'],
            'callback_patterns': v['callback_patterns'],
            'required_macros': v['required_macros'],
        })


def unseed_vendors(apps, schema_editor):
    MMP = apps.get_model('mmp', 'MMP')
    MMP.objects.filter(vendor__in=[v['vendor'] for v in VENDORS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mmp', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_vendors, reverse_code=unseed_vendors),
    ]

from django.db import migrations


def create_default_brand_and_backfill(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    brand, _ = Brand.objects.get_or_create(
        slug='nexora',
        defaults={
            'name': 'Nexora',
            'primary_domain': 'cpa.cloudtrade.pro',
            'tracking_domain': 't.cloudtrade.pro',
            'support_email': 'support@cloudtrade.pro',
            'primary_color': '#6366f1',
            'secondary_color': '#4f46e5',
            'is_default': True,
        },
    )
    # Ensure is_default is set in case the brand row already existed
    if not brand.is_default:
        brand.is_default = True
        brand.save(update_fields=['is_default', 'updated_at'])

    apps.get_model('offer', 'Offer').objects.filter(brand__isnull=True).update(brand=brand)
    apps.get_model('offer', 'Advertiser').objects.filter(brand__isnull=True).update(brand=brand)
    apps.get_model('tracker', 'Click').objects.filter(brand__isnull=True).update(brand=brand)
    apps.get_model('tracker', 'Conversion').objects.filter(brand__isnull=True).update(brand=brand)
    apps.get_model('user_profile', 'Profile').objects.filter(brand__isnull=True).update(brand=brand)


def remove_default_brand(apps, schema_editor):
    apps.get_model('brands', 'Brand').objects.filter(slug='nexora').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
        ('offer', '0026_advertiser_brand'),
        ('tracker', '0016_click_conversion_brand'),
        ('user_profile', '0005_profile_brand'),
    ]

    operations = [
        migrations.RunPython(
            create_default_brand_and_backfill,
            remove_default_brand,
        ),
    ]

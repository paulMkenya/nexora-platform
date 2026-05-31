import pytest
from brands.models import Brand


@pytest.fixture
def default_brand(db):
    return Brand.objects.create(
        slug='nexora-test',
        name='Nexora',
        primary_domain='cpa.test.com',
        tracking_domain='t.test.com',
        is_default=True,
    )


@pytest.fixture
def second_brand(db):
    return Brand.objects.create(
        slug='acme',
        name='Acme Network',
        primary_domain='app.acme.com',
        tracking_domain='t.acme.com',
        is_default=False,
    )


class TestBrandModel:
    def test_str(self, default_brand):
        assert str(default_brand) == 'Nexora'

    def test_get_default_returns_is_default(self, default_brand, second_brand):
        assert Brand.get_default() == default_brand

    def test_get_default_falls_back_to_first(self, db, second_brand):
        # Clear is_default on all brands (including the migration-seeded brand)
        Brand.objects.all().update(is_default=False)
        assert Brand.get_default() == Brand.objects.order_by('id').first()

    def test_setting_new_default_clears_old(self, default_brand, second_brand):
        second_brand.is_default = True
        second_brand.save()
        default_brand.refresh_from_db()
        assert not default_brand.is_default
        assert Brand.objects.filter(is_default=True).count() == 1

    def test_only_one_default_at_a_time(self, default_brand):
        b2 = Brand.objects.create(
            slug='b2', name='B2', primary_domain='b2.com',
            tracking_domain='t.b2.com', is_default=True,
        )
        default_brand.refresh_from_db()
        assert not default_brand.is_default
        assert b2.is_default

    def test_colors_default(self, db):
        b = Brand.objects.create(
            slug='colortest', name='Color', primary_domain='color.com', tracking_domain='t.color.com',
        )
        assert b.primary_color == '#6366f1'
        assert b.secondary_color == '#4f46e5'

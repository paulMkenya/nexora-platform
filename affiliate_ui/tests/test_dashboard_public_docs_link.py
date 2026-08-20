"""The dashboard surfaces the login-free doc link.

The affiliate is rarely the person who writes the integration — their developer
or their traffic source is, and that person has no portal account. Before this
the only way to hand over the contract was to download a PDF and email it, and
an emailed PDF goes stale: on 2026-08-20 `country` went from optional to
enforced and every copy already sent started describing behaviour that no longer
existed. A link cannot go stale.

The assertion that matters is the HOST one. This string exists to be copied out
of the page and pasted into an email, so it must be absolute and must carry the
affiliate's OWN brand domain — never the domain they happened to be browsing.
"""
import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()

DASHBOARD = '/partner/dashboard/'
OWN_HOST = 'own-brand.test'
OTHER_HOST = 'other-brand.test'


@pytest.fixture
def own_brand(db):
    # tracking_domain is UNIQUE, so two fixtures both leaving it blank collide.
    return Brand.objects.create(slug='own-brand', name='OwnNet',
                                primary_domain=OWN_HOST, tracking_domain=f't.{OWN_HOST}',
                                is_default=False)


@pytest.fixture
def other_brand(db):
    return Brand.objects.create(slug='other-brand', name='OtherNet',
                                primary_domain=OTHER_HOST, tracking_domain=f't.{OTHER_HOST}',
                                is_default=True)


@pytest.fixture
def affiliate(db, own_brand):
    u = User.objects.create_user(username='dash_aff', password='x', email='d@aff.test')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.brand = own_brand
    u.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    u.profile.email_verified = True
    u.profile.save()
    return u


@pytest.mark.django_db
def test_dashboard_shows_the_public_docs_link(client, affiliate, own_brand):
    client.force_login(affiliate)
    body = client.get(DASHBOARD, HTTP_HOST=OWN_HOST, secure=True).content.decode()
    assert '/partner/api-docs/public/' in body
    assert 'Shareable link' in body


@pytest.mark.django_db
def test_the_link_is_absolute(client, affiliate, own_brand):
    """A relative href is useless the moment it is pasted into an email."""
    client.force_login(affiliate)
    body = client.get(DASHBOARD, HTTP_HOST=OWN_HOST, secure=True).content.decode()
    assert f'https://{OWN_HOST}/partner/api-docs/public/' in body


@pytest.mark.django_db
def test_the_link_carries_the_affiliates_own_brand_not_the_browsed_host(
        client, affiliate, own_brand, other_brand):
    """Affiliate login is not brand-gated, so an affiliate can reach the portal
    on another tenant's domain. Handing them THAT hostname to send to their
    traffic source would point real leads at the wrong tenant."""
    client.force_login(affiliate)
    body = client.get(DASHBOARD, HTTP_HOST=OTHER_HOST, secure=True).content.decode()
    assert f'https://{OWN_HOST}/partner/api-docs/public/' in body
    assert OTHER_HOST not in body


@pytest.mark.django_db
def test_the_link_actually_resolves(client, affiliate, own_brand):
    """Guards against the panel advertising a URL that 404s."""
    resp = client.get('/partner/api-docs/public/', HTTP_HOST=OWN_HOST, secure=True)
    assert resp.status_code == 200

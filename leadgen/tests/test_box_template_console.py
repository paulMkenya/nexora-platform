"""The template catalogue and the template-driven buyer form (Phase 1, part 2).

Brand admins may now create templates, so the scoping tests here are the ones
that matter. Two rules, both easy to get wrong and expensive to get wrong:

  * a brand operator SEES platform templates (brand null) plus their own, and
    nobody else's — a rival tenant's template names their integration partner;
  * a brand operator EDITS only their own. Platform templates are readable by
    everyone and writable by the owner alone, because every other tenant's
    buyers are built on them.
"""
import pytest
from django.contrib.auth import get_user_model

from leadgen.models import BoxType, LeadBuyer
from user_profile.models import Profile

User = get_user_model()

LIST = '/admin/distribution/templates/'


@pytest.fixture
def other_brand(db):
    from brands.models import Brand
    return Brand.objects.create(slug='rival', name='Rival Network',
                                primary_domain='rival.test', tracking_domain='t.rival.test')


@pytest.fixture
def brand_operator(db, brand):
    """A staff operator bound to one brand — not a superuser."""
    u = User.objects.create_user(username='tpl_operator', password='x', is_staff=True)
    u.profile.role = Profile.Role.NETWORK_ADMIN
    u.profile.brand = brand
    u.profile.save(update_fields=['role', 'brand'])
    return u


@pytest.fixture
def owner(db):
    return User.objects.create_superuser(username='tpl_owner', password='x', email='o@t.test')


@pytest.fixture
def platform_tpl(db):
    return BoxType.objects.create(
        name='Hypernet Platform', slug='tpl-platform', brand=None,
        connector_class='leadgen.connectors.HypernetConnector',
        variable_schema=[
            {'name': 'affc', 'label': 'Affiliate code', 'required': True,
             'help': 'Ask the buyer for it.'},
            {'name': 'secret_token', 'label': 'Secret token', 'secret': True},
        ])


@pytest.fixture
def own_tpl(db, brand):
    return BoxType.objects.create(
        name='Our Own Box', slug='tpl-own', brand=brand,
        connector_class='leadgen.connectors.LeadBuyerConnector')


@pytest.fixture
def rival_tpl(db, other_brand):
    return BoxType.objects.create(
        name='Rival Secret Box', slug='tpl-rival', brand=other_brand,
        connector_class='leadgen.connectors.LeadBuyerConnector')


# --- visibility ---------------------------------------------------------------

@pytest.mark.django_db
def test_operator_sees_platform_and_own_but_not_a_rivals(
        client, brand_operator, platform_tpl, own_tpl, rival_tpl):
    client.force_login(brand_operator)
    body = client.get(LIST).content.decode()
    assert platform_tpl.name in body
    assert own_tpl.name in body
    assert rival_tpl.name not in body, "another tenant's template names their integration partner"


@pytest.mark.django_db
def test_owner_sees_everything(client, owner, platform_tpl, own_tpl, rival_tpl):
    client.force_login(owner)
    body = client.get(LIST).content.decode()
    for tpl in (platform_tpl, own_tpl, rival_tpl):
        assert tpl.name in body


@pytest.mark.django_db
def test_a_rivals_template_is_not_reachable_by_id(client, brand_operator, rival_tpl):
    """Not merely hidden from the list — unreachable."""
    client.force_login(brand_operator)
    assert client.get(f'{LIST}{rival_tpl.pk}/').status_code == 404
    assert client.get(f'{LIST}{rival_tpl.pk}/edit/').status_code == 404


# --- edit rights --------------------------------------------------------------

@pytest.mark.django_db
def test_operator_cannot_edit_a_platform_template(client, brand_operator, platform_tpl):
    """Readable, not writable: every other tenant's buyers are built on it. 403
    rather than 404 because the operator can plainly see it in the list, so
    hiding it would just be confusing."""
    client.force_login(brand_operator)
    assert client.get(f'{LIST}{platform_tpl.pk}/').status_code == 200
    assert client.get(f'{LIST}{platform_tpl.pk}/edit/').status_code == 403


@pytest.mark.django_db
def test_operator_can_edit_their_own_template(client, brand_operator, own_tpl):
    client.force_login(brand_operator)
    assert client.get(f'{LIST}{own_tpl.pk}/edit/').status_code == 200


@pytest.mark.django_db
def test_operator_cannot_create_a_platform_wide_template(client, brand_operator, brand):
    """The brand field is locked to their own brand. A platform template is
    offered to every tenant, so letting one publish into that shared space puts
    their recipe in front of everyone else's operators."""
    client.force_login(brand_operator)
    resp = client.post(f'{LIST}new/', data={
        'name': 'Sneaky Platform Template', 'slug': 'sneaky', 'brand': '',
        'version': 1, 'description': '',
        'connector_class': 'leadgen.connectors.LeadBuyerConnector',
        'auth_type': 'api_key_query', 'auth_param_name': 'apiKey',
        'single_endpoint_path': '/leads', 'batch_endpoint_path': '',
        'fetch_endpoint_path': '/leads', 'deposits_endpoint_path': '',
        'batch_max_size': 1, 'rate_limit_burst': 10,
        'rate_limit_refill_tokens': 1, 'rate_limit_refill_seconds': 1,
        'default_field_mapping': '{}', 'default_status_mapping': '{}',
        'variable_schema': '[]',
    })
    created = BoxType.objects.filter(slug='sneaky').first()
    if created is not None:
        assert created.brand_id == brand.pk, 'must not land as a platform template'
    else:
        assert resp.status_code == 200, 'rejected is also acceptable'


@pytest.mark.django_db
def test_an_unregistered_connector_is_refused_by_the_form(client, brand_operator, brand):
    client.force_login(brand_operator)
    client.post(f'{LIST}new/', data={
        'name': 'RCE Attempt', 'slug': 'rce', 'brand': brand.pk, 'version': 1,
        'description': '', 'connector_class': 'os.system',
        'auth_type': 'api_key_query', 'auth_param_name': 'apiKey',
        'single_endpoint_path': '/leads', 'batch_endpoint_path': '',
        'fetch_endpoint_path': '/leads', 'deposits_endpoint_path': '',
        'batch_max_size': 1, 'rate_limit_burst': 10,
        'rate_limit_refill_tokens': 1, 'rate_limit_refill_seconds': 1,
        'default_field_mapping': '{}', 'default_status_mapping': '{}',
        'variable_schema': '[]',
    })
    assert not BoxType.objects.filter(slug='rce').exists()


# --- the buyer form renders from the template --------------------------------

@pytest.mark.django_db
def test_buyer_form_renders_the_templates_variables(client, brand_operator, platform_tpl):
    """The whole point: real labelled fields with help text, not a JSON textarea."""
    client.force_login(brand_operator)
    body = client.get(f'/admin/distribution/buyers/add/?box_type={platform_tpl.pk}').content.decode()
    assert 'Affiliate code' in body
    assert 'Ask the buyer for it.' in body
    assert 'var__affc' in body


@pytest.mark.django_db
def test_a_secret_variable_renders_as_a_password_field(client, brand_operator, platform_tpl):
    client.force_login(brand_operator)
    body = client.get(f'/admin/distribution/buyers/add/?box_type={platform_tpl.pk}').content.decode()
    assert 'type="password"' in body, 'a secret must not be a plain text input'


@pytest.mark.django_db
def test_variables_are_saved_and_secrets_stay_out_of_the_plaintext_column(
        client, brand_operator, brand, platform_tpl):
    client.force_login(brand_operator)
    client.post('/admin/distribution/buyers/add/', data={
        'box_type': platform_tpl.pk, 'brand': brand.pk,
        'name': 'Built From Template', 'slug': 'from-template',
        'base_url': 'https://box.example.com', 'is_active': 'on',
        'field_mapping': '{}', 'status_mapping': '{}',
        'extra_payload_fields': '{}', 'pinned_payload_fields': '[]',
        'api_key': 'k', 'var__affc': 'AFF-FROM-FORM', 'var__secret_token': 'sh-hh',
    })
    buyer = LeadBuyer.objects.filter(slug='from-template').first()
    assert buyer is not None, 'the form should have saved'
    assert buyer.extra_payload_fields.get('affc') == 'AFF-FROM-FORM'
    assert 'sh-hh' not in str(buyer.extra_payload_fields), \
        'extra_payload_fields is plaintext and rendered to operators'
    assert buyer.get_extra_credentials().get('secret_token') == 'sh-hh'


@pytest.mark.django_db
def test_saving_preserves_keys_the_template_does_not_declare(
        client, brand_operator, brand, platform_tpl):
    """A box may legitimately carry a key added by hand before the template
    gained a schema. Dropping it on the next save would break a live
    integration with no error to read."""
    buyer = LeadBuyer.objects.create(
        brand=brand, box_type=platform_tpl, name='Has Extras', slug='has-extras',
        base_url='https://box.example.com',
        extra_payload_fields={'affc': 'OLD', 'handAdded': 'keep-me'})
    client.force_login(brand_operator)
    client.post(f'/admin/distribution/buyers/{buyer.pk}/edit/', data={
        'box_type': platform_tpl.pk, 'brand': brand.pk,
        'name': 'Has Extras', 'slug': 'has-extras',
        'base_url': 'https://box.example.com', 'is_active': 'on',
        'field_mapping': '{}', 'status_mapping': '{}',
        'extra_payload_fields': '{"affc": "OLD", "handAdded": "keep-me"}',
        'pinned_payload_fields': '[]', 'var__affc': 'NEW',
    })
    buyer.refresh_from_db()
    assert buyer.extra_payload_fields.get('affc') == 'NEW', 'declared variable updated'
    assert buyer.extra_payload_fields.get('handAdded') == 'keep-me', 'undeclared key preserved'


@pytest.mark.django_db
def test_a_template_with_no_schema_still_works(client, brand_operator, own_tpl):
    """Absence of a declaration must never mean absence of the capability —
    every pre-existing template starts with an empty schema."""
    client.force_login(brand_operator)
    resp = client.get(f'/admin/distribution/buyers/add/?box_type={own_tpl.pk}')
    assert resp.status_code == 200
    assert 'var__' not in resp.content.decode()

"""Self-describing BoxType templates (Phase 1).

Two things are being tested, and only one of them is a feature.

THE FEATURE: a template declares the variables a buyer on it needs, so adding a
box on a known platform is a form to fill in rather than an engineering task.
Before this, what a Hypernet box required lived in a hard-coded dict in a
management command, in connector class attributes, and in somebody's memory —
the console offered a raw JSON textarea and no hint of what belonged in it.

THE GUARD, which matters more: brand admins may now create templates
(Paul's decision, 2026-08-20). `connector_class` is fed to `import_string`, so a
free-text field would let whoever edits a template choose which code runs on the
delivery path. It is now a registry choice, enforced in `clean()`, and the
registry lives in Python where a form cannot reach it. The tests below must keep
failing loudly if anyone relaxes that.
"""
import pytest
from django.core.exceptions import ValidationError

from leadgen.box_variables import (
    SchemaError, effective_schema, missing_required, normalize, split_values,
    validate_variable_schema,
)
from leadgen.connector_registry import CONNECTORS, connector_choices, is_registered
from leadgen.models import BoxType


def _box(**kw):
    defaults = dict(
        name='Probe', slug='probe-box',
        connector_class='leadgen.connectors.LeadBuyerConnector',
        variable_schema=[],
    )
    defaults.update(kw)
    return BoxType(**defaults)


# --- the guard ----------------------------------------------------------------

@pytest.mark.django_db
def test_an_unregistered_connector_is_refused():
    """The whole reason connector_class stopped being free text."""
    box = _box(connector_class='django.contrib.auth.models.User')
    with pytest.raises(ValidationError) as exc:
        box.full_clean()
    assert 'connector_class' in exc.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize('path', sorted(CONNECTORS))
def test_every_registered_connector_is_accepted_and_importable(path):
    """A registry entry naming a class that does not exist would fail at
    delivery time, on a real lead, rather than here."""
    from django.utils.module_loading import import_string

    assert import_string(path) is not None
    _box(connector_class=path).full_clean()


def test_the_registry_is_not_database_backed():
    """It lives in code on purpose: a table an operator can write to would
    defeat the point of having an allowlist at all."""
    assert isinstance(CONNECTORS, dict) and CONNECTORS
    assert is_registered('leadgen.connectors.HypernetConnector')
    assert not is_registered('django.contrib.auth.models.User')
    assert all(isinstance(v, str) and v for v in CONNECTORS.values()), 'every entry needs a description'
    assert len(connector_choices()) == len(CONNECTORS)


# --- schema validation --------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('bad,why', [
    ('not-a-list', 'must be a list'),
    ([{'name': '9leading-digit'}], 'name charset'),
    ([{'name': 'ok'}, {'name': 'ok'}], 'duplicate name'),
    ([{'name': 'ok', 'required': 'yes'}], 'required must be bool'),
    ([{'name': 'ok', 'surprise': 1}], 'unknown key'),
    ([{'name': 'ok', 'label': 5}], 'label must be text'),
    (['just a string'], 'entry must be an object'),
])
def test_a_malformed_schema_cannot_be_saved(bad, why):
    """It is validated on SAVE because the buyer form renders straight from it —
    a bad entry would otherwise surface as a broken page at the exact moment
    someone is onboarding a buyer."""
    with pytest.raises(ValidationError) as exc:
        _box(variable_schema=bad).full_clean()
    assert 'variable_schema' in exc.value.message_dict, why


def test_validate_accepts_a_well_formed_schema():
    schema = [{'name': 'affc', 'label': 'Affiliate code', 'required': True},
              {'name': 'lang', 'default': 'en'}]
    assert validate_variable_schema(schema) == schema


def test_normalize_fills_every_optional_key_and_keeps_order():
    got = normalize([{'name': 'b'}, {'name': 'a', 'label': 'A', 'secret': True}])
    assert [v['name'] for v in got] == ['b', 'a'], 'order is the form order, chosen deliberately'
    assert got[0] == {'name': 'b', 'label': 'b', 'help': '', 'required': False,
                      'secret': False, 'default': ''}
    assert got[1]['secret'] is True


# --- the split is a security boundary ----------------------------------------

@pytest.mark.django_db
def test_secret_variables_never_land_in_the_plaintext_column():
    """extra_payload_fields is plaintext JSON rendered back to operators in the
    console. A variable marked secret must go to the encrypted store instead —
    the exact exposure LeadBuyer.api_key_encrypted exists to avoid."""
    box = _box(variable_schema=[
        {'name': 'affc', 'required': True},
        {'name': 'password', 'secret': True},
    ])
    payload, secrets = split_values(box, {'affc': 'AFF-1', 'password': 'hunter2'})
    assert payload == {'affc': 'AFF-1'}
    assert secrets == {'password': 'hunter2'}
    assert 'hunter2' not in str(payload)


@pytest.mark.django_db
def test_blank_values_are_omitted_not_sent_empty():
    """For several boxes in this vertical an empty string is a real value that
    overwrites a default, while an absent key leaves the default alone."""
    box = _box(variable_schema=[{'name': 'a'}, {'name': 'b'}])
    payload, _ = split_values(box, {'a': 'set', 'b': '   '})
    assert payload == {'a': 'set'}


@pytest.mark.django_db
def test_defaults_apply_when_a_value_is_not_supplied():
    box = _box(variable_schema=[{'name': 'lang', 'default': 'en'}])
    payload, _ = split_values(box, {})
    assert payload == {'lang': 'en'}


@pytest.mark.django_db
def test_missing_required_names_only_the_required_ones():
    box = _box(variable_schema=[
        {'name': 'affc', 'required': True},
        {'name': 'bxc', 'required': True},
        {'name': 'note', 'required': False},
    ])
    assert missing_required(box, {'affc': 'x'}) == ['bxc']
    assert missing_required(box, {'affc': 'x', 'bxc': 'y'}) == []


# --- absence of a declaration is not absence of capability --------------------

@pytest.mark.django_db
def test_a_template_with_no_schema_is_legal():
    """Every pre-existing template starts empty. That must mean "falls back to
    the raw JSON editor", never "this template is broken"."""
    assert effective_schema(_box(variable_schema=[])) == []
    assert effective_schema(None) == []
    _box(variable_schema=[]).full_clean()


# --- brand ownership ----------------------------------------------------------

@pytest.mark.django_db
def test_a_platform_template_has_no_brand(brand):
    """NULL = available to every brand. The OPPOSITE of the rule for offers, and
    deliberately so: a BoxType is an outbound integration recipe holding no
    credentials and no counterparty, so sharing it leaks nothing."""
    box = _box(slug='platform-tpl')
    box.full_clean()
    box.save()
    assert box.brand_id is None

    owned = _box(slug='brand-tpl', brand=brand)
    owned.full_clean()
    owned.save()
    assert owned.brand_id == brand.pk


# --- the backfill -------------------------------------------------------------

@pytest.mark.django_db
def test_backfill_fills_empty_schemas_and_leaves_edited_ones_alone():
    from django.core.management import call_command

    hypernet = BoxType.objects.create(
        name='Hypernet', slug='hypernet',
        connector_class='leadgen.connectors.HypernetConnector')
    edited = BoxType.objects.create(
        name='TrackBox', slug='trackbox',
        connector_class='leadgen.connectors.TrackBoxConnector',
        variable_schema=[{'name': 'mine', 'label': 'Hand edited'}])

    call_command('backfill_box_variable_schemas')

    hypernet.refresh_from_db()
    edited.refresh_from_db()
    names = [v['name'] for v in hypernet.variable_schema]
    assert {'affc', 'bxc', 'vtc', 'funnel'} <= set(names), 'the knowledge that was hard-coded'
    assert edited.variable_schema == [{'name': 'mine', 'label': 'Hand edited'}], \
        'a hand edit is newer information than the backfill file'


@pytest.mark.django_db
def test_backfilled_schemas_are_themselves_valid():
    """Guards the backfill file against a typo that would only surface as a
    broken onboarding form."""
    from leadgen.management.commands.backfill_box_variable_schemas import SCHEMAS

    for slug, schema in SCHEMAS.items():
        try:
            validate_variable_schema(schema)
        except SchemaError as exc:
            pytest.fail(f'{slug}: {exc}')

"""BoxType.variable_schema — the declaration that lets a template describe its
own onboarding, and the code that turns a filled-in form back into a buyer.

A schema is a list of entries:

    {"name": "affc", "label": "Affiliate code",
     "help": "Hypernet issues this per box — ask your account manager.",
     "required": true, "secret": false, "default": ""}

`name` is the key the connector will actually send (BoxType/LeadBuyer field
mappings and extra_payload_fields both key off it), so it is validated against
the same character set a JSON payload key can safely carry.

WHY VALIDATION IS STRICT HERE. The buyer form renders straight from this list.
A malformed entry does not fail quietly in a test — it surfaces as a broken page
at the exact moment someone is trying to onboard a buyer, which is the worst
time to discover it. Validated on save (BoxType.clean) so a bad schema can never
reach a form.
"""
import re

NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]{0,39}$')

ALLOWED_KEYS = {'name', 'label', 'help', 'required', 'secret', 'default'}
MAX_VARIABLES = 40


class SchemaError(ValueError):
    pass


def validate_variable_schema(schema):
    """Raise SchemaError unless `schema` is a well-formed variable list."""
    if schema in (None, ''):
        return []
    if not isinstance(schema, list):
        raise SchemaError('Must be a list of variable definitions.')
    if len(schema) > MAX_VARIABLES:
        raise SchemaError(f'At most {MAX_VARIABLES} variables.')

    seen = set()
    for index, entry in enumerate(schema, 1):
        name = _validate_entry(entry, where=f'Variable {index}')
        if name in seen:
            raise SchemaError(f'Variable {index}: duplicate variable name "{name}".')
        seen.add(name)
    return schema


def _validate_entry(entry, *, where):
    """Validate one variable definition and return its name. Split out from
    validate_variable_schema so each function stays readable — the loop is about
    uniqueness across entries, this is about the shape of one."""
    if not isinstance(entry, dict):
        raise SchemaError(f'{where}: each entry must be an object.')

    unknown = set(entry) - ALLOWED_KEYS
    if unknown:
        raise SchemaError(
            f'{where}: unknown key(s) {", ".join(sorted(unknown))}. '
            f'Allowed: {", ".join(sorted(ALLOWED_KEYS))}.')

    name = entry.get('name')
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise SchemaError(
            f'{where}: "name" must start with a letter or underscore and use only '
            f'letters, digits, "_", "." and "-" (40 characters max).')

    for flag in ('required', 'secret'):
        if flag in entry and not isinstance(entry[flag], bool):
            raise SchemaError(f'{where}: "{flag}" must be true or false.')
    for text in ('label', 'help'):
        if text in entry and not isinstance(entry[text], str):
            raise SchemaError(f'{where}: "{text}" must be text.')
    return name


def normalize(schema):
    """The schema with every optional key filled in, so renderers and callers
    never have to guess a default. Order is preserved — it is the order the
    fields appear on the form, and a template author controls it deliberately."""
    out = []
    for entry in validate_variable_schema(schema) or []:
        name = entry['name']
        out.append({
            'name': name,
            'label': entry.get('label') or name,
            'help': entry.get('help', ''),
            'required': bool(entry.get('required', False)),
            'secret': bool(entry.get('secret', False)),
            'default': entry.get('default', ''),
        })
    return out


def effective_schema(box_type):
    """`box_type`'s declared variables, or [] for a template that declares none
    (every pre-existing template, until backfilled). An empty schema means the
    buyer form falls back to its raw JSON editor rather than showing nothing —
    absence of a declaration must never mean absence of the capability."""
    if box_type is None:
        return []
    return normalize(getattr(box_type, 'variable_schema', None) or [])


def missing_required(box_type, values):
    """Names of required variables `values` does not supply a non-empty value
    for. Used by the buyer form; kept here so the form and any future importer
    or management command agree on what "complete" means."""
    return [
        var['name'] for var in effective_schema(box_type)
        if var['required'] and not str(values.get(var['name'], '') or '').strip()
    ]


def split_values(box_type, values):
    """Split submitted variables into (payload_constants, secrets).

    THE SPLIT IS A SECURITY BOUNDARY, not tidiness. `extra_payload_fields` is
    plaintext JSON rendered back to operators in the console; anything marked
    `secret` must go to LeadBuyer.set_extra_credentials() (Fernet at rest)
    instead. Putting a password in the plaintext column is exactly the exposure
    LeadBuyer.api_key_encrypted exists to avoid, and it is a one-word mistake to
    make when hand-editing JSON — which is precisely what this feature removes.
    """
    payload, secrets = {}, {}
    for var in effective_schema(box_type):
        raw = values.get(var['name'], var['default'])
        if raw is None:
            continue
        raw = str(raw).strip()
        if not raw:
            continue
        (secrets if var['secret'] else payload)[var['name']] = raw
    return payload, secrets

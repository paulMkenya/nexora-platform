"""Pins the DATABASE-level defaults on leadgen_lead.attribution / .language.

These exist so a schema change can land ahead of the code that uses it without
killing lead capture — see migration 0017. The failure they prevent is not
theoretical: applying 0016 in production on 2026-08-17, while the previous
release was still serving, broke every INSERT immediately, because Django drops
a field default at the DB level after using it to backfill.

The test is written against the raw column, deliberately NOT through the ORM.
Going through the ORM would prove nothing — it always supplies both values, so
it cannot observe whether the database could fill them on its own, which is the
entire property under test.
"""
import pytest
from django.db import connection

EXPECTED_DEFAULTS = {
    'attribution': "'{}'::jsonb",
    'language': "''::character varying",
}


def _column_defaults():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name, column_default, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'leadgen_lead'
              AND column_name IN ('attribution', 'language')
        """)
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


@pytest.mark.django_db
class TestLeadColumnDefaults:
    @pytest.mark.parametrize('column,expected', sorted(EXPECTED_DEFAULTS.items()))
    def test_column_has_a_database_level_default(self, column, expected):
        defaults = _column_defaults()
        assert column in defaults, f'{column} missing from leadgen_lead'
        actual, _ = defaults[column]
        assert actual == expected, (
            f'{column} has no usable DB default ({actual!r}). An INSERT that does not name '
            f'it will fail, which is how a deploy takes lead capture down.')

    def test_an_insert_omitting_both_columns_succeeds(self):
        """The actual guarantee, exercised the way old code hits it: an INSERT
        naming neither column, as the previous release's ORM emits when its
        model predates the fields.

        Every OTHER not-null column without a default is filled generically
        rather than listed by hand, so this test keeps testing its own subject
        as the model grows instead of failing on some unrelated new column.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'leadgen_lead'
                  AND is_nullable = 'NO'
                  AND column_default IS NULL
                  AND column_name NOT IN ('id', 'attribution', 'language')
            """)
            required = cursor.fetchall()

        # A minimal legal value per type — the point is a successful INSERT,
        # not realistic data.
        def placeholder(data_type):
            if data_type in ('jsonb', 'json'):
                return "'{}'::jsonb"
            if data_type in ('timestamp with time zone', 'timestamp without time zone'):
                return 'now()'
            if data_type == 'boolean':
                return 'false'
            if data_type in ('integer', 'bigint', 'smallint', 'numeric'):
                return '0'
            return "''"

        columns = ', '.join(name for name, _ in required)
        values = ', '.join(placeholder(dtype) for _, dtype in required)

        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO leadgen_lead ({columns}) VALUES ({values}) '
                'RETURNING id, attribution, language')
            lead_id, attribution, language = cursor.fetchone()
            # The columns nobody named were filled BY THE DATABASE — which is
            # precisely what the running-but-older release depends on.
            #
            # Compared loosely on purpose: a raw cursor may hand jsonb back as
            # the string '{}' rather than a dict depending on which psycopg2
            # adapters are registered. The claim under test is "the database
            # supplied an empty object", not how this driver types it.
            assert attribution in ({}, '{}')
            assert language == ''
            cursor.execute('DELETE FROM leadgen_lead WHERE id = %s', [lead_id])

    def test_both_columns_remain_not_null(self):
        """The defaults are the fix, not loosening the constraint — these stay
        NOT NULL so neither field can silently become null."""
        for _column, (_default, is_nullable) in _column_defaults().items():
            assert is_nullable == 'NO'

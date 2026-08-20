"""Django's `{# #}` comment syntax is SINGLE-LINE ONLY.

A `{#` whose `#}` is on a later line is not a comment at all — the template
engine emits every character of it verbatim into the response. Nobody notices,
because the text usually lands in <head> or between block elements where a
browser does not paint it; it is only visible in View Source, which is exactly
where the people we least want reading it look.

This was live on 2026-08-20 in six templates. The one that mattered:
platform_leads/get_started.html shipped

    {# Honeypot — hidden from humans; bots that fill it are silently dropped.
       The name is a neutral, non-autofill token on purpose... #}

to every anonymous visitor of /get-started/, which is a public page. The comment
explains the anti-bot mechanism, names the field, and says what happens when it
is filled — served, in the page, to the bots it exists to catch.

So this is not a style rule. A repo-wide scan is the only reliable guard,
because the failure is invisible in every normal review and in the rendered
page.
"""
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Other agents' checkouts and build output — not ours to police.
SKIP_PARTS = ('node_modules', 'staticfiles', '.claude', 'site-packages', '.git')


def _templates():
    for path in REPO_ROOT.rglob('*.html'):
        if any(part in path.parts for part in SKIP_PARTS):
            continue
        yield path


def test_no_multiline_django_comments_anywhere():
    offenders = []
    for path in _templates():
        try:
            lines = path.read_text(errors='ignore').splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            # A `{#` with no `#}` on the SAME line cannot be a valid comment.
            if '{#' in line and '#}' not in line:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f'{rel}:{number}: {line.strip()[:80]}')

    assert not offenders, (
        'These are NOT comments — Django renders them into the response '
        'verbatim. Use {% comment %}...{% endcomment %} for anything spanning '
        'more than one line:\n  ' + '\n  '.join(offenders)
    )


@pytest.mark.django_db
def test_the_honeypot_explanation_is_not_served_to_visitors(client):
    """The specific regression: /get-started/ is public, and its source used to
    describe the honeypot to anyone reading it."""
    body = client.get('/get-started/').content.decode()
    assert 'Honeypot' not in body
    assert 'silently dropped' not in body
    # The field itself must still be there — we removed the explanation, not
    # the defence.
    assert 'hp_check' in body

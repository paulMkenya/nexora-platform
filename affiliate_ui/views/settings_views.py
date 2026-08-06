"""Company Settings — the affiliate's own account settings.

Activates the nav placeholder that has read "SOON" since the shell was built.
Everything here is backed by a field the application already reads; nothing was
invented to fill the page out.

The page is deliberately split by consequence:

  * Editable here — name and country. Benign: they affect how the affiliate is
    addressed and what geo their leads are stamped with, and a wrong value is
    corrected by typing a better one.

  * Read-only here, edited on their own existing pages — payout methods and
    settings, API keys, postback configuration. Every one of those is a money
    or credential path, already has a working page, and is already guarded by
    block_when_not_fully_authed. Rebuilding an edit path for them here would
    create a second writer for the same setting, which is how the two copies
    drift apart; linking is the honest option.

  * Read-only, deliberately not editable anywhere — the account email. It is
    not the login identity (auth is username-based via ModelBackend), but it IS
    the password-reset destination, so being able to change it turns a stolen
    session into durable account takeover: set your own address, trigger a
    reset, own the account after the real user regains their password. The
    usual defence is step-up re-authentication — re-enter your password to
    change this — and this codebase has no step-up mechanism. Rather than ship
    the change without the protection that makes it safe, the field is shown
    and routed to support. See docs/adr if step-up is ever added.
"""
import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_not_fully_authed
from user_profile.geo import country_choices

logger = logging.getLogger(__name__)

# Only these move. Anything absent from this tuple cannot be written by this
# view even if it is posted — see _apply_changes.
EDITABLE_USER_FIELDS = ('first_name', 'last_name')
EDITABLE_PROFILE_FIELDS = ('country',)


def _settings_context(request):
    user = request.user
    profile = getattr(user, 'profile', None)
    return {
        'user_obj': user,
        'profile': profile,
        'country_choices': country_choices(),
        'current_country': getattr(profile, 'country', '') or '',
    }


@require_approved_affiliate
def company_settings(request):
    return render(request, 'affiliate_ui/settings.html', _settings_context(request))


def _apply_changes(request):
    """Write the allow-listed fields, returning [(field, old, new)] actually
    changed. Values are read from POST by explicit name — a field not in the
    two tuples above is unreachable from here regardless of what is posted."""
    user = request.user
    profile = getattr(user, 'profile', None)
    changed = []

    user_dirty = []
    for field in EDITABLE_USER_FIELDS:
        new = (request.POST.get(field) or '').strip()[:150]
        old = getattr(user, field, '') or ''
        if new != old:
            setattr(user, field, new)
            user_dirty.append(field)
            changed.append((field, old, new))
    if user_dirty:
        user.save(update_fields=user_dirty)

    if profile is not None:
        valid = {code for code, _label in country_choices(include_blank=False)}
        profile_dirty = []
        for field in EDITABLE_PROFILE_FIELDS:
            new = (request.POST.get(field) or '').strip().upper()
            # An unknown code is dropped rather than stored: country is stamped
            # onto leads (leads/services.py), so a junk value would propagate.
            if field == 'country' and new and new not in valid:
                messages.error(request, 'That country was not recognised — leaving it unchanged.')
                continue
            old = getattr(profile, field, '') or ''
            if new != old:
                setattr(profile, field, new)
                profile_dirty.append(field)
                changed.append((field, old, new))
        if profile_dirty:
            profile.save(update_fields=profile_dirty)

    return changed


@block_when_not_fully_authed
@require_approved_affiliate
@require_POST
def company_settings_update(request):
    """Save the benign fields.

    block_when_not_fully_authed is applied for consistency with every other
    affiliate write, not because these fields are sensitive: it means an
    operator impersonating this affiliate cannot quietly rewrite their details.
    """
    changed = _apply_changes(request)

    if changed:
        # Structured, not a new audit model. These fields are benign, so this
        # is operational history rather than a security event — the brief's
        # audit requirement applies to sensitive settings, and none are
        # writable here.
        logger.info(
            'company_settings updated user=%s fields=%s',
            request.user.pk, [f for f, _o, _n in changed],
        )
        messages.success(request, 'Your settings have been saved.')
    else:
        messages.info(request, 'No changes to save.')

    return redirect('affiliate_ui:company_settings')

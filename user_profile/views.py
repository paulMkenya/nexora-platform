from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from user_profile.models import Profile


@require_POST
@login_required
def set_theme(request):
    """Persist the user's UI theme preference (dark/light).

    Best-effort: the front-end already applied the theme and stored it in
    localStorage; this makes the choice durable on the profile so it survives
    devices/sessions. Users without a profile (rare) just get an ok no-op.
    """
    theme = request.POST.get('theme')
    valid = {Profile.Theme.DARK, Profile.Theme.LIGHT}
    if theme not in valid:
        return JsonResponse({'ok': False, 'error': 'invalid theme'}, status=400)

    profile = getattr(request.user, 'profile', None)
    if profile is not None and profile.theme_preference != theme:
        profile.theme_preference = theme
        profile.save(update_fields=['theme_preference'])

    return JsonResponse({'ok': True, 'theme': theme})

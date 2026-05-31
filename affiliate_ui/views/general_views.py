from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Prefetch
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.views import LoginView
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from offer.models import Offer, Category, Payout, ACTIVE_STATUS
from tracker.models import Click, Conversion, APPROVED_STATUS
from user_profile.models import Profile


@login_required
def dashboard(request):
    clicks_count = Click.objects.filter(affiliate=request.user).count()

    conversions = Conversion.objects.filter(affiliate=request.user)
    conversions_count = conversions.count()

    total_earnings = conversions.filter(
        status=APPROVED_STATUS).aggregate(total=Sum('payout'))['total'] or 0

    try:
        profile = request.user.profile
        is_pending = (
            profile.role == Profile.Role.AFFILIATE
            and (
                profile.affiliate_status != Profile.AffiliateStatus.APPROVED
                or not profile.email_verified
            )
        )
    except Exception:
        is_pending = False

    context = {
        'clicks_count': clicks_count,
        'conversions_count': conversions_count,
        'total_earnings': f'{total_earnings:.2f}',
        'is_pending': is_pending,
    }
    return render(request, 'affiliate_ui/dashboard.html', context)


@require_approved_affiliate
def offer_list(request):
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', None)

    offers = Offer.objects.prefetch_related(
        Prefetch('payouts', queryset=Payout.objects.order_by('-payout'))
    ).filter(status=ACTIVE_STATUS)

    if search_query:
        offers = offers.filter(title__icontains=search_query)

    if category_id:
        offers = offers.filter(categories__id=category_id)

    categories = Category.objects.all()

    context = {
        'offers': offers,
        'categories': categories,
        'search_query': search_query,
        'selected_category': int(category_id) if category_id else None,
    }
    return render(request, 'affiliate_ui/offers.html', context)


def generate_tracking_link(offer_id: int, pid: int) -> str:
    base_url = settings.TRACKER_URL
    url = f"{base_url}/click?offer_id={offer_id}&pid={pid}"
    return url


@require_POST
@login_required
def affiliate_logout(request):
    auth_logout(request)
    return redirect('/')


@require_approved_affiliate
def offer_detail(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    tracking_link = generate_tracking_link(offer_id, request.user.id)
    context = {
        'offer': offer,
        'tracking_link': tracking_link,
    }
    return render(request, 'affiliate_ui/offer_details.html', context)


class AffiliateLoginView(LoginView):
    template_name = 'affiliate_ui/login.html'
    redirect_authenticated_user = True

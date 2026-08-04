from django.urls import path

from . import public_views
from .api_views import (
    LeadBatchSubmitView, LeadDetailView, LeadListView, LeadStatusListView, LeadSubmitView,
)

app_name = 'leadgen'

urlpatterns = [
    # Inbound API (affiliates) — Authorization: ApiKey <secret>
    path('api/leads/submit', LeadSubmitView.as_view(), name='api-submit'),
    path('api/leads/submit/batch', LeadBatchSubmitView.as_view(), name='api-submit-batch'),
    path('api/leads/statuses', LeadStatusListView.as_view(), name='api-statuses'),
    path('api/leads/<int:pk>', LeadDetailView.as_view(), name='api-detail'),
    path('api/leads', LeadListView.as_view(), name='api-list'),

    # Public, unauthenticated capture page — one per Offer, for direct ad
    # traffic (FB/Google/etc).
    path('l/<int:offer_id>/', public_views.capture_lead, name='capture'),
]

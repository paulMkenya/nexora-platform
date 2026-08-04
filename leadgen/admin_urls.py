from django.urls import path

from . import admin_views

app_name = 'leadgen_console'

urlpatterns = [
    path('leads/', admin_views.leads_console, name='leads'),
    path('leads/route-now/', admin_views.route_now, name='route_now'),
    path('leads/<int:pk>/status/', admin_views.lead_status_flip, name='lead_status_flip'),
    path('buyers/', admin_views.buyers_list, name='buyers'),
    path('buyers/add/', admin_views.buyer_form, name='buyer_add'),
    path('buyers/<int:pk>/edit/', admin_views.buyer_form, name='buyer_edit'),
    path('buyers/<int:pk>/test-connection/', admin_views.buyer_test_connection, name='buyer_test_connection'),
    path('routing-rules/', admin_views.routing_rules_list, name='routing_rules'),
    path('routing-rules/add/', admin_views.routing_rule_form, name='routing_rule_add'),
    path('routing-rules/<int:pk>/edit/', admin_views.routing_rule_form, name='routing_rule_edit'),
    # Affiliate Inbound API spec Phase 6 — operator mirror controls
    path('affiliate-links/', admin_views.affiliate_offer_links_list, name='affiliate_offer_links'),
    path('affiliate-links/<int:pk>/go-live/', admin_views.affiliate_offer_link_go_live,
         name='affiliate_offer_link_go_live'),
    path('affiliate-links/<int:pk>/revert/', admin_views.affiliate_offer_link_revert,
         name='affiliate_offer_link_revert'),
]

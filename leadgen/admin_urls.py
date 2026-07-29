from django.urls import path

from . import admin_views

app_name = 'leadgen_console'

urlpatterns = [
    path('leads/', admin_views.leads_console, name='leads'),
    path('leads/route-now/', admin_views.route_now, name='route_now'),
    path('buyers/', admin_views.buyers_list, name='buyers'),
    path('buyers/add/', admin_views.buyer_form, name='buyer_add'),
    path('buyers/<int:pk>/edit/', admin_views.buyer_form, name='buyer_edit'),
    path('buyers/<int:pk>/test-connection/', admin_views.buyer_test_connection, name='buyer_test_connection'),
    path('routing-rules/', admin_views.routing_rules_list, name='routing_rules'),
    path('routing-rules/add/', admin_views.routing_rule_form, name='routing_rule_add'),
    path('routing-rules/<int:pk>/edit/', admin_views.routing_rule_form, name='routing_rule_edit'),
]

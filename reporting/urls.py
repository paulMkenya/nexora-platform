from django.urls import path

from .views import ClicksReportView, ConversionsReportView, RevenueReportView

urlpatterns = [
    path('reports/clicks', ClicksReportView.as_view(), name='report-clicks'),
    path('reports/conversions', ConversionsReportView.as_view(), name='report-conversions'),
    path('reports/revenue', RevenueReportView.as_view(), name='report-revenue'),
]

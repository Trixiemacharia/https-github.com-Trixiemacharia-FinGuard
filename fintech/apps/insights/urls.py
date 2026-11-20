from django.urls import path

from .views import (FinancialCalendarEntryView, InsightsDashboardView, FinancialCalendarUpcomingView, FinancialCalendarView, InsightsOverviewView, MonthlyReportView, RecurringDetectionView,
                    RecurringDetectionStatusView, RecurringPaymentView, TransactionCategoryView)

urlpatterns = [
    path("", InsightsOverviewView.as_view(), name="insights-overview"),
    path("dashboard/", InsightsDashboardView.as_view(), name="insights-dashboard"),
    path("transactions/", TransactionCategoryView.as_view(), name="insights-transactions"),
    path("reports/<int:year>/<int:month>/", MonthlyReportView.as_view(), name="insights-monthly-report"),
    path("transactions/<str:transaction_id>/category/", TransactionCategoryView.as_view(), name="insights-transaction-category"),
    path("recurring/detection/", RecurringDetectionView.as_view(), name="insights-recurring-detection"),
    path("recurring/detection/<str:task_id>/", RecurringDetectionStatusView.as_view(), name="insights-recurring-detection-status"),
    path("recurring/<int:payment_id>/", RecurringPaymentView.as_view(), name="insights-recurring-payment"),
    path("calendar/", FinancialCalendarView.as_view(), name="insights-calendar"),
    path("calendar/upcoming/", FinancialCalendarUpcomingView.as_view(), name="insights-calendar-upcoming"),
    path("calendar/<int:entry_id>/", FinancialCalendarEntryView.as_view(), name="insights-calendar-entry"),
]

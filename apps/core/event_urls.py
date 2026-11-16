from django.urls import path

from apps.fraud.views import CustomerNotificationsView, CustomerWsTicketView

urlpatterns = [
    path("notifications/", CustomerNotificationsView.as_view(), name="customer-notifications"),
    path("ws-ticket/", CustomerWsTicketView.as_view(), name="customer-ws-ticket"),
]

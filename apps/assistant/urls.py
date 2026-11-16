from django.urls import path

from .views import AssistantCapabilitiesView, AssistantQueryView

urlpatterns = [
    path("capabilities/", AssistantCapabilitiesView.as_view(), name="assistant-capabilities"),
    path("query/", AssistantQueryView.as_view(), name="assistant-query"),
]

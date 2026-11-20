from django.urls import path

from .views import AssistantCapabilitiesView, AssistantQueryView, AssistantRunCreateView, AssistantRunDetailView

urlpatterns = [
    path("capabilities/", AssistantCapabilitiesView.as_view(), name="assistant-capabilities"),
    path("query/", AssistantQueryView.as_view(), name="assistant-query"),
    path("runs/", AssistantRunCreateView.as_view(), name="assistant-runs"),
    path("runs/<uuid:run_id>/", AssistantRunDetailView.as_view(), name="assistant-run-detail"),
]

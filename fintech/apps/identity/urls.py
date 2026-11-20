from django.urls import path

from . import views

urlpatterns = [
    path("consent/", views.ConsentView.as_view(), name="identity-consent"),
    path("liveness/challenge/", views.ChallengeView.as_view(), name="identity-challenge"),
    path("liveness/preview/", views.PreviewView.as_view(), name="identity-preview"),
    path("liveness/verify/", views.VerifyView.as_view(), name="identity-liveness"),
    path("review/", views.ReviewQueueView.as_view(), name="identity-review-queue"),
    path("review/<int:user_id>/asset/<str:asset>/", views.ReviewAssetView.as_view(), name="identity-review-asset"),
    path("review/<int:user_id>/decision/", views.ReviewDecisionView.as_view(), name="identity-review-decision"),
]

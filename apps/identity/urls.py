from django.urls import path

from . import views

urlpatterns = [
    path("google/nonce/", views.GoogleNonceView.as_view(), name="onboarding-google-nonce"),
    path("google/", views.GoogleVerifyView.as_view(), name="onboarding-google"),
    path("state/", views.StateView.as_view(), name="onboarding-state"),
    path("consent/", views.ConsentView.as_view(), name="onboarding-consent"),
    path("photo/", views.PhotoView.as_view(), name="onboarding-photo"),
    path("liveness/challenge/", views.ChallengeView.as_view(), name="onboarding-challenge"),
    path("liveness/preview/", views.PreviewView.as_view(), name="onboarding-preview"),
    path("liveness/verify/", views.LivenessVerifyView.as_view(), name="onboarding-liveness"),
    path("phone/send/", views.PhoneSendView.as_view(), name="onboarding-phone-send"),
    path("phone/verify/", views.PhoneVerifyView.as_view(), name="onboarding-phone-verify"),
    path("details/", views.DetailsView.as_view(), name="onboarding-details"),
    path("complete/", views.CompleteView.as_view(), name="onboarding-complete"),
    path("review/", views.ReviewQueueView.as_view(), name="identity-review-queue"),
    path("review/<uuid:registration_id>/asset/<str:asset>/", views.ReviewAssetView.as_view(), name="identity-review-asset"),
    path("review/<uuid:registration_id>/decision/", views.ReviewDecisionView.as_view(), name="identity-review-decision"),
]

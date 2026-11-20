from django.urls import path

from apps.users.views import (
    GoogleExchangeView,
    GoogleNonceView,
    GoogleAuthView,
    LoginView,
    LogoutView,
    MfaVerifyView,
    RefreshView,
    RegisterView,
    google_login_finish,
    OnboardingView,
    OnboardingReviewView,
    CurrentUserView,
    SessionsView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("mfa/verify/", MfaVerifyView.as_view(), name="auth-mfa-verify"),
    path("google/", GoogleAuthView.as_view(), name="auth-google"),
    path("google/nonce/", GoogleNonceView.as_view(), name="auth-google-nonce"),
    path("google/finish/", google_login_finish, name="auth-google-finish"),
    path("google/exchange/", GoogleExchangeView.as_view(), name="auth-google-exchange"),
    path("token/refresh/", RefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
    path("sessions/", SessionsView.as_view(), name="auth-sessions"),
    path("sessions/<str:jti>/", SessionsView.as_view(), name="auth-session-revoke"),
    path("onboarding/", OnboardingView.as_view(), name="auth-onboarding"),
    path("onboarding/review/<int:user_id>/", OnboardingReviewView.as_view(), name="auth-onboarding-review"),
]

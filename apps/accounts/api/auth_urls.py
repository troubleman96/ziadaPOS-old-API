"""
apps/accounts/api/auth_urls.py

Authentication URL routes.
Mounted at: /api/v1/auth/

Endpoints:
  POST /api/v1/auth/register/       → owner self-registration (org + store + trial)
  POST /api/v1/auth/login/          → phone + password → JWT access + refresh + user profile
  POST /api/v1/auth/refresh/        → refresh token → new access token
  POST /api/v1/auth/verify/         → verify a token is still valid
  POST /api/v1/auth/forgot-password/ → request password reset token
  POST /api/v1/auth/reset-password/   → confirm reset token and set new password

NOTE: The default TokenObtainPairView (username+password) is replaced by
PhoneLoginView (phone+password). The refresh and verify endpoints are unchanged.
"""

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenRefreshView,
    TokenVerifyView,
)

from .views import (
    ConfirmEmailView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PhoneLoginView,
    RegisterView,
    ResendConfirmationView,
)

urlpatterns = [
    # Self-registration — creates org, store, owner user, trial subscription
    path("register/", RegisterView.as_view(),     name="register"),

    # Phone-based login — returns access + refresh tokens + user profile
    path("login/",    PhoneLoginView.as_view(),   name="login"),

    # Refresh — POST { refresh } → { access }
    path("refresh/",  TokenRefreshView.as_view(), name="token_refresh"),

    # Verify — POST { token } → 200 OK or 401
    path("verify/",   TokenVerifyView.as_view(),  name="token_verify"),

    # Email confirmation — GET ?token=<uuid> (link from the welcome email)
    path("confirm-email/",        ConfirmEmailView.as_view(),       name="confirm-email"),

    # Resend confirmation — POST (authenticated) when user hasn't confirmed yet
    path("resend-confirmation/",  ResendConfirmationView.as_view(), name="resend-confirmation"),

    # Password reset — request token
    path("forgot-password/",      PasswordResetRequestView.as_view(),  name="forgot-password"),

    # Password reset — confirm with token and set new password
    path("reset-password/",       PasswordResetConfirmView.as_view(),  name="reset-password"),
]

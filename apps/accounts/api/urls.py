"""
apps/accounts/api/urls.py

Account management URL routes.
Mounted at: /api/v1/accounts/

Endpoints:
  GET/PATCH   /api/v1/accounts/me/                     → current user profile + subscription status
  POST        /api/v1/accounts/me/switch-store/        → owner switches active store
  POST        /api/v1/accounts/me/change-password/     → change password
  POST        /api/v1/accounts/me/verify-phone/send/    → send phone OTP (SendAfrica)
  POST        /api/v1/accounts/me/verify-phone/confirm/ → verify phone OTP
  GET/POST    /api/v1/accounts/users/                  → list / create staff
  GET/PATCH   /api/v1/accounts/users/{id}/             → staff detail / update
  GET         /api/v1/accounts/users/{id}/stats/       → staff performance stats
  GET         /api/v1/accounts/users/kpis/             → org/store staff KPIs
  GET/POST    /api/v1/accounts/stores/                 → list / create stores
  GET/PATCH   /api/v1/accounts/stores/{id}/            → store detail / update
  GET/PATCH   /api/v1/accounts/organisation/           → org settings
  GET         /api/v1/accounts/organisation/sms-balance/ → SendAfrica SMS credit balance
  GET         /api/v1/accounts/ai-credits/             → AI credit usage (sidenav)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AICreditView,
    ChangePasswordView,
    MeView,
    OrganisationSmsBalanceView,
    OrganisationView,
    SendPhoneOTPView,
    StoreViewSet,
    SwitchStoreView,
    UserViewSet,
    VerifyPhoneOTPView,
)

router = DefaultRouter()
router.register(r"users",  UserViewSet,  basename="user")
# basename="account-store" avoids collision with apps/stores/api/urls.py which uses "store"
router.register(r"stores", StoreViewSet, basename="account-store")

urlpatterns = [
    path("me/",                 MeView.as_view(),             name="me"),
    path("me/switch-store/",    SwitchStoreView.as_view(),    name="switch-store"),
    path("me/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("me/verify-phone/send/",    SendPhoneOTPView.as_view(),   name="verify-phone-send"),
    path("me/verify-phone/confirm/", VerifyPhoneOTPView.as_view(), name="verify-phone-confirm"),
    path("organisation/",       OrganisationView.as_view(),   name="organisation"),
    path("organisation/sms-balance/", OrganisationSmsBalanceView.as_view(), name="organisation-sms-balance"),
    path("ai-credits/",         AICreditView.as_view(),       name="ai-credits"),
    path("", include(router.urls)),
]

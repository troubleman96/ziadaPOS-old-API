"""
apps/accounts/api/urls.py

Account management URL routes.
Mounted at: /api/v1/accounts/

Endpoints:
  GET/PATCH   /api/v1/accounts/me/                     → current user profile + subscription status
  POST        /api/v1/accounts/me/change-password/     → change password
  GET/POST    /api/v1/accounts/users/                  → list / create staff
  GET/PATCH   /api/v1/accounts/users/{id}/             → staff detail / update
  GET         /api/v1/accounts/users/{id}/stats/       → staff performance stats
  GET         /api/v1/accounts/users/kpis/             → org/store staff KPIs
  GET/POST    /api/v1/accounts/stores/                 → list / create stores
  GET/PATCH   /api/v1/accounts/stores/{id}/            → store detail / update
  GET/PATCH   /api/v1/accounts/organisation/           → org settings
  GET         /api/v1/accounts/ai-credits/             → AI credit usage (sidenav)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AICreditView,
    ChangePasswordView,
    MeView,
    OrganisationView,
    StoreViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register(r"users",  UserViewSet,  basename="user")
router.register(r"stores", StoreViewSet, basename="store")

urlpatterns = [
    path("me/",                 MeView.as_view(),             name="me"),
    path("me/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("organisation/",       OrganisationView.as_view(),   name="organisation"),
    path("ai-credits/",         AICreditView.as_view(),       name="ai-credits"),
    path("", include(router.urls)),
]

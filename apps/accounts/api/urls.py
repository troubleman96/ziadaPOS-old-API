"""
apps/accounts/api/urls.py

Account management URL routes.
Mounted at: /api/v1/accounts/

Endpoints:
  GET/PATCH   /api/v1/accounts/me/                     → current user profile
  POST        /api/v1/accounts/me/change-password/     → change password
  GET/POST    /api/v1/accounts/users/                  → list / create users
  GET/PATCH   /api/v1/accounts/users/{id}/             → user detail / update
  GET/POST    /api/v1/accounts/stores/                 → list / create stores
  GET/PATCH   /api/v1/accounts/stores/{id}/            → store detail / update
  GET/PATCH   /api/v1/accounts/organisation/           → org settings
  GET         /api/v1/accounts/ai-credits/             → AI credit usage
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

# Router auto-generates CRUD routes for ViewSets
router = DefaultRouter()
router.register(r"users",  UserViewSet,  basename="user")
router.register(r"stores", StoreViewSet, basename="store")

urlpatterns = [
    # Current user profile
    path("me/",                    MeView.as_view(),             name="me"),
    path("me/change-password/",    ChangePasswordView.as_view(), name="change-password"),

    # Organisation settings
    path("organisation/",          OrganisationView.as_view(),   name="organisation"),

    # AI credit usage (sidenav footer widget)
    path("ai-credits/",            AICreditView.as_view(),       name="ai-credits"),

    # ViewSet routes (users/, users/{id}/, stores/, stores/{id}/)
    path("", include(router.urls)),
]

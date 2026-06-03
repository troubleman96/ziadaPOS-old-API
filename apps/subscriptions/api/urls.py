"""
apps/subscriptions/api/urls.py

Mounted at: /api/v1/subscriptions/

Public (AllowAny):
  GET  /api/v1/subscriptions/plans/                    → pricing plans list
  GET  /api/v1/subscriptions/plans/{id}/               → plan detail

Authenticated owner:
  GET  /api/v1/subscriptions/my-subscription/          → owner's active subscription
  GET  /api/v1/subscriptions/store-limit/              → can-add-store check + pricing

Cameltech admin only:
  POST   /api/v1/subscriptions/plans/                  → create a plan
  PATCH  /api/v1/subscriptions/plans/{id}/             → update a plan
  DELETE /api/v1/subscriptions/plans/{id}/             → deactivate a plan
  GET    /api/v1/subscriptions/all/                    → all subscriptions
  GET    /api/v1/subscriptions/all/{id}/               → subscription detail
  POST   /api/v1/subscriptions/all/{id}/activate/      → confirm payment + activate
  PATCH  /api/v1/subscriptions/all/{id}/extra-stores/  → grant extra store slots
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MySubscriptionView,
    StoreLimitView,
    SubscriptionPlanViewSet,
    SubscriptionViewSet,
)

router = DefaultRouter()
router.register(r"plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register(r"all",   SubscriptionViewSet,     basename="subscription")

urlpatterns = [
    path("my-subscription/", MySubscriptionView.as_view(), name="my-subscription"),
    path("store-limit/",     StoreLimitView.as_view(),     name="store-limit"),
    path("", include(router.urls)),
]

"""
apps/subscriptions/api/urls.py

Mounted at: /api/v1/subscriptions/

Endpoints:
  GET/POST   /api/v1/subscriptions/plans/                   → plan list/create
  GET/PATCH  /api/v1/subscriptions/plans/{id}/              → plan detail/update
  DELETE     /api/v1/subscriptions/plans/{id}/              → deactivate plan

  GET        /api/v1/subscriptions/my-subscription/         → owner's subscription

  GET        /api/v1/subscriptions/all/                     → admin: all subscriptions
  GET        /api/v1/subscriptions/all/{id}/                → admin: subscription detail
  POST       /api/v1/subscriptions/all/{id}/activate/       → admin: confirm payment
  PATCH      /api/v1/subscriptions/all/{id}/extra-stores/   → admin: add extra stores
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MySubscriptionView, SubscriptionPlanViewSet, SubscriptionViewSet

router = DefaultRouter()
router.register(r"plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register(r"all",   SubscriptionViewSet,     basename="subscription")

urlpatterns = [
    path("my-subscription/", MySubscriptionView.as_view(), name="my-subscription"),
    path("", include(router.urls)),
]

"""
apps/customers/api/urls.py

Customer routes. Mounted at: /api/v1/customers/

  GET    /                   → list customers (segmented, filtered, paginated)
  POST   /                   → create new customer
  GET    /{id}/              → customer detail
  PATCH  /{id}/              → update customer info / segment
  DELETE /{id}/              → soft-delete
  GET    /summary/           → KPI aggregate stats
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet

router = DefaultRouter()
router.register(r"", CustomerViewSet, basename="customer")

urlpatterns = [
    path("", include(router.urls)),
]

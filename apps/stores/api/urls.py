"""
apps/stores/api/urls.py

Mounted at: /api/v1/stores/

Endpoints:
  GET    /                  → list stores with live KPIs
  POST   /                  → create store (admin)
  GET    /stats/            → org KPI header strip
  GET    /{id}/             → store detail (week chart + staff roster)
  PATCH  /{id}/             → update store settings
  DELETE /{id}/             → deactivate store (admin)
  GET    /{id}/staff/       → staff roster
  GET    /{id}/week/        → 7-day revenue breakdown
  PATCH  /{id}/status/      → quick status toggle (open/closed/paused)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import StoreViewSet

router = DefaultRouter()
router.register(r"", StoreViewSet, basename="store")

urlpatterns = [
    path("", include(router.urls)),
]

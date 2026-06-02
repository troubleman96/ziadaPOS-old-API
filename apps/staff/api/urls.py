"""
apps/staff/api/urls.py

Mounted at: /api/v1/staff/

Router-generated endpoints:
  GET    /                       list  (?role= ?status= ?shift= ?search= ?ordering=)
  POST   /                       create staff member
  GET    /kpis/                  store-level KPI summary
  GET    /{id}/                  detail with computed stats
  PATCH  /{id}/                  update profile fields
  DELETE /{id}/                  deactivate (soft delete)
  GET    /{id}/stats/            performance stats only
  PATCH  /{id}/shift/            update shift + employment_status
  PATCH  /{id}/permissions/      update can_refund / can_discount / can_view_reports
  GET    /{id}/activity/         today's transaction activity (?date=YYYY-MM-DD)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import StaffViewSet

router = DefaultRouter()
router.register(r"", StaffViewSet, basename="staff")

urlpatterns = [
    path("", include(router.urls)),
]

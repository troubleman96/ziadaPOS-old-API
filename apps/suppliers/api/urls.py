"""
apps/suppliers/api/urls.py

Mounted at: /api/v1/suppliers/

Router-generated endpoints:
  GET    /                        → supplier list
  POST   /                        → create supplier
  GET    /stats/                  → KPI header stats
  GET    /{id}/                   → supplier detail
  PATCH  /{id}/                   → update supplier
  DELETE /{id}/                   → deactivate supplier
  GET    /{id}/deliveries/        → deliveries for this supplier
  POST   /{id}/deliveries/        → add a delivery
  GET    /{id}/payments/          → payments for this supplier
  POST   /{id}/pay/               → record a payment

  GET    /deliveries/             → all deliveries (supports ?unpaid=true, ?supplier=)
  POST   /deliveries/             → create delivery
  GET    /deliveries/{id}/        → delivery detail
  PATCH  /deliveries/{id}/        → update delivery
  DELETE /deliveries/{id}/        → delete delivery
  POST   /deliveries/{id}/pay/    → mark delivery paid

  GET    /payments/               → all payments (supports ?supplier=)
  GET    /payments/{id}/          → payment detail
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SupplierDeliveryViewSet, SupplierPaymentViewSet, SupplierViewSet

router = DefaultRouter()
router.register(r"deliveries", SupplierDeliveryViewSet, basename="supplier-delivery")
router.register(r"payments",   SupplierPaymentViewSet,  basename="supplier-payment")
router.register(r"",           SupplierViewSet,          basename="supplier")

urlpatterns = [
    path("", include(router.urls)),
]

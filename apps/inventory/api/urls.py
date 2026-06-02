"""
apps/inventory/api/urls.py

Inventory API routes. Mounted at: /api/v1/inventory/

Category endpoints (categories auto-created via ProductSerializer too):
  GET    /categories/              → list with live product count
  GET    /categories/{id}/         → detail
  POST   /categories/              → create (or return existing, case-insensitive)
  PATCH  /categories/{id}/         → rename / reorder

Product endpoints:
  GET    /products/                → list (filterable: category, status, is_active, minimal)
  POST   /products/                → create (category_name_input auto-creates category)
  GET    /products/{id}/           → detail
  PATCH  /products/{id}/           → update
  DELETE /products/{id}/           → soft-archive (is_active=False)
  GET    /products/by-barcode/     → ?code=<barcode> exact match (POS scan)
  GET    /products/low-stock/      → products at or below reorder point
  POST   /products/{id}/adjust-stock/  → manual stock adjustment
  GET    /products/{id}/adjustments/   → stock movement history
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductViewSet

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products",   ProductViewSet,   basename="product")

urlpatterns = [
    path("", include(router.urls)),
]

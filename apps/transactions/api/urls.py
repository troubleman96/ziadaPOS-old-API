"""
apps/transactions/api/urls.py

Transaction routes. Mounted at: /api/v1/transactions/

  GET    /                   → list transactions (filtered, paginated)
  GET    /{id}/              → transaction detail (with lines)
  GET    /summary/           → KPI aggregate stats
  POST   /{id}/refund/       → refund a transaction
  POST   /complete-sale/     → POS checkout (create transaction from cart)
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CompleteSaleView, TransactionViewSet

router = DefaultRouter()
router.register(r"", TransactionViewSet, basename="transaction")

urlpatterns = [
    # POS checkout — must come BEFORE the router to avoid conflict with /{id}/
    path("complete-sale/", CompleteSaleView.as_view(), name="complete-sale"),

    # ViewSet routes (list, detail, summary, refund)
    path("", include(router.urls)),
]

"""
apps/inventory/api/views.py

API views for inventory management (Products, Categories, StockAdjustments).
Supplier views live in apps.suppliers.api.views.

Category auto-create:
  CategoryViewSet is now a full ModelViewSet — categories can be created on the
  fly from the inventory UI (or via ProductSerializer's `category_name_input`
  field). Neither workflow requires pre-seeding categories through admin.
"""

import logging

from django.db import transaction as db_transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import IsStoreManager
from apps.core.response import created_response, error_response, success_response

from ..models import Category, Product, StockAdjustment
from .serializers import (
    CategorySerializer,
    CategoryWriteSerializer,
    ManualStockAdjustmentSerializer,
    ProductMinimalSerializer,
    ProductSerializer,
    StockAdjustmentSerializer,
)

logger = logging.getLogger(__name__)


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryViewSet(ModelViewSet):
    """
    Categories for product classification.

    READ (anyone authenticated):
      GET  /api/v1/inventory/categories/        → all categories with live product count
      GET  /api/v1/inventory/categories/{id}/   → single category

    WRITE (manager / admin):
      POST   /api/v1/inventory/categories/        → create a new category
      PATCH  /api/v1/inventory/categories/{id}/   → update name / description / sort_order

    DELETE is intentionally excluded — deleting a category that has products
    assigned to it would leave those products uncategorised. Use PATCH to
    rename or reorder instead.

    The ProductSerializer also creates categories automatically via the
    `category_name_input` field — this endpoint is for explicit management.
    """

    queryset = Category.objects.all()
    pagination_class = None   # very few categories — never paginate
    http_method_names = ["get", "post", "patch", "head", "options"]  # no DELETE

    def get_permissions(self):
        if self.request.method in ("POST", "PATCH"):
            return [IsAuthenticated(), IsStoreManager()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method in ("POST", "PATCH"):
            return CategoryWriteSerializer
        return CategorySerializer

    def list(self, request, *args, **kwargs):
        serializer = CategorySerializer(self.get_queryset(), many=True)
        return success_response(
            data=serializer.data,
            message=f"{len(serializer.data)} categories.",
        )

    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/inventory/categories/

        Create a new category. If a category with the same name already exists
        (case-insensitive), returns the existing one instead of erroring — so
        the frontend can call this without a prior existence check.
        """
        name = (request.data.get("name") or "").strip()
        if not name:
            return error_response("Category name is required.", status=400)

        # Case-insensitive dedup: return existing rather than 409
        existing = Category.objects.filter(name__iexact=name).first()
        if existing:
            return success_response(
                data=CategorySerializer(existing).data,
                message=f"Category '{existing.name}' already exists.",
            )

        serializer = CategoryWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        category = serializer.save()
        logger.info("User %s created category '%s'.", request.user.username, category.name)
        return created_response(
            data=CategorySerializer(category).data,
            message=f"Category '{category.name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        category = self.get_object()
        serializer = CategoryWriteSerializer(category, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=CategorySerializer(category).data,
            message="Category updated.",
        )


# ── Product ───────────────────────────────────────────────────────────────────

class ProductViewSet(ModelViewSet):
    """
    Full CRUD for products.

    LIST  GET /api/v1/inventory/products/
      Query params:
        ?category=Grocery        → filter by category name
        ?status=low|out|critical → stock-based filter
        ?search=unga             → name / SKU / barcode search
        ?ordering=-weekly_sold   → sort (e.g. dashboard top sellers)
        ?is_active=true          → POS uses this to show only active products
        ?minimal=true            → lean response for POS grid

    BARCODE GET /api/v1/inventory/products/by-barcode/?code=6160100012413
      Exact barcode match — used by POS "Scan" button.

    LOW STOCK GET /api/v1/inventory/products/low-stock/

    ADJUST STOCK POST /api/v1/inventory/products/{id}/adjust-stock/

    HISTORY GET /api/v1/inventory/products/{id}/adjustments/
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "price", "cost", "stock", "weekly_sold", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = Product.objects.select_related(
            "category", "supplier", "store"
        ).filter(
            store=self.request.user.store
        )

        # Category name filter (?category=Grocery)
        category = self.request.query_params.get("category")
        if category and category.lower() != "all":
            qs = qs.filter(category__name__iexact=category)

        # Stock status filter (?status=low|out|critical)
        stock_status = self.request.query_params.get("status")
        if stock_status == "low":
            from django.db.models import F
            qs = qs.filter(stock__lte=F("min_stock"), stock__gt=0)
        elif stock_status == "out":
            qs = qs.filter(stock=0)
        elif stock_status == "critical":
            from django.db.models import ExpressionWrapper, FloatField, F
            qs = qs.filter(
                stock__lte=ExpressionWrapper(
                    F("min_stock") * 0.4,
                    output_field=FloatField(),
                ),
                stock__gt=0,
            )

        # Active filter (?is_active=true|false)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        else:
            qs = qs.filter(is_active=True)

        return qs

    def get_serializer_class(self):
        if self.request.query_params.get("minimal") == "true":
            return ProductMinimalSerializer
        return ProductSerializer

    # ── Standard CRUD ─────────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        return success_response(
            data=ProductSerializer(product).data,
            message="Product retrieved.",
        )

    def create(self, request, *args, **kwargs):
        """
        Create a new product.
        Store is injected from the authenticated user — clients cannot override it.
        Category is auto-created if `category_name_input` is supplied and the
        category does not already exist.
        Accepts multipart/form-data so an optional `image` file can be uploaded.
        """
        data = request.data.copy()
        data["store"] = str(request.user.store_id)

        serializer = ProductSerializer(data=data, context={"request": request})
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        product = serializer.save()
        logger.info(
            "User %s created product '%s' (SKU: %s).",
            request.user.username, product.name, product.sku,
        )
        return created_response(
            data=ProductSerializer(product, context={"request": request}).data,
            message=f"Product '{product.name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        product = self.get_object()
        serializer = ProductSerializer(
            product, data=request.data, partial=True, context={"request": request}
        )
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        logger.info("User %s updated product '%s'.", request.user.username, product.name)
        return success_response(
            data=ProductSerializer(product, context={"request": request}).data,
            message="Product updated.",
        )

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
        logger.info("User %s archived product '%s'.", request.user.username, product.name)
        return success_response(message=f"Product '{product.name}' archived.")

    # ── Extra actions ──────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="by-barcode")
    def by_barcode(self, request):
        """
        GET /api/v1/inventory/products/by-barcode/?code=6160100012413

        Exact barcode match — used by the POS "Scan" button.
        Returns a single product (or 404 if not found).
        Always returns the minimal representation so the POS can add it to the
        cart immediately without a second request.
        """
        code = request.query_params.get("code", "").strip()
        if not code:
            return error_response("Query param 'code' is required.", status=400)

        try:
            product = Product.objects.get(
                barcode=code,
                store=request.user.store,
                is_active=True,
            )
        except Product.DoesNotExist:
            return error_response(
                f"No active product with barcode '{code}' found in this store.",
                status=404,
            )

        return success_response(
            data=ProductMinimalSerializer(product).data,
            message="Product found.",
        )

    @action(detail=False, methods=["get"], url_path="low-stock",
            permission_classes=[IsAuthenticated])
    def low_stock(self, request):
        """
        GET /api/v1/inventory/products/low-stock/
        Products at or below their reorder point (most urgent first).
        """
        from django.db.models import F
        qs = self.get_queryset().filter(
            stock__lte=F("min_stock"),
            is_active=True,
        ).order_by("stock")

        serializer = ProductSerializer(qs, many=True)
        return success_response(
            data=serializer.data,
            meta={"count": len(serializer.data)},
            message=f"{len(serializer.data)} products below reorder point.",
        )

    @action(detail=True, methods=["post"], url_path="adjust-stock",
            permission_classes=[IsAuthenticated, IsStoreManager])
    def adjust_stock(self, request, pk=None):
        """
        POST /api/v1/inventory/products/{id}/adjust-stock/
        Body: { "quantity_change": -5, "note": "Damaged goods" }
        """
        product = self.get_object()
        serializer = ManualStockAdjustmentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        delta = serializer.validated_data["quantity_change"]
        note  = serializer.validated_data["note"]

        with db_transaction.atomic():
            before = product.stock
            product.stock += delta
            product.save(update_fields=["stock", "updated_at"])

            StockAdjustment.objects.create(
                product=product,
                adjustment_type=StockAdjustment.TYPE_MANUAL,
                quantity_change=delta,
                quantity_before=before,
                quantity_after=product.stock,
                note=note,
                performed_by=request.user,
            )

        logger.info(
            "User %s manually adjusted stock of '%s' by %d (note: %s).",
            request.user.username, product.name, delta, note,
        )
        return success_response(
            data=ProductSerializer(product).data,
            message=f"Stock adjusted by {delta:+d}. New stock: {product.stock}.",
        )

    @action(detail=True, methods=["get"], url_path="adjustments")
    def adjustments(self, request, pk=None):
        """
        GET /api/v1/inventory/products/{id}/adjustments/
        Full stock movement history for a product.
        """
        product = self.get_object()
        adj_qs = StockAdjustment.objects.filter(product=product).select_related(
            "performed_by"
        )
        page = self.paginate_queryset(adj_qs)
        if page is not None:
            serializer = StockAdjustmentSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = StockAdjustmentSerializer(adj_qs, many=True)
        return success_response(data=serializer.data)

"""
apps/inventory/api/serializers.py

Serializers for inventory: Categories, Products, StockAdjustments.
Supplier serializers live in apps.suppliers.api.serializers.

Category auto-create:
  ProductSerializer accepts `category_name` (string) in addition to `category`
  (UUID FK). When a name is provided, the category is looked up case-insensitively
  and created if it does not yet exist — so callers never need to pre-create
  categories through a separate workflow.
"""

from rest_framework import serializers

from ..models import Category, Product, StockAdjustment


# ── Category ──────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "description", "sort_order", "is_global", "count", "created_at"]
        read_only_fields = ["id", "is_global", "created_at"]

    def get_count(self, obj):
        return obj.products.filter(is_active=True).count()


class CategoryWriteSerializer(serializers.ModelSerializer):
    """
    Used by POST /api/v1/inventory/categories/ (CategoryViewSet.create).
    Accepts name + optional description/sort_order.
    """

    class Meta:
        model = Category
        fields = ["id", "name", "description", "sort_order"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Category name cannot be blank.")
        return value


# ── Product (POS-minimal) ─────────────────────────────────────────────────────

class ProductMinimalSerializer(serializers.ModelSerializer):
    """
    Lean product representation for the POS product grid (?minimal=true).

    Includes all fields the POS needs:
      id, name, sku, barcode → identity / barcode scan
      price                  → shown on card and used in cart total
      stock                  → low-stock badge (≤5 = bad, ≤15 = warn)
      stock_status           → 'active' | 'low' | 'critical' | 'out'
      color                  → card avatar colour scheme
      category_name          → category filter pill matching
      image_url              → absolute URL to product image (null if none)
    """

    stock_status  = serializers.CharField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    image_url     = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "sku", "barcode",
            "price", "stock", "stock_status",
            "color", "unit",
            "category", "category_name",
            "image_url",
        ]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


# ── Product (full) ────────────────────────────────────────────────────────────

class ProductSerializer(serializers.ModelSerializer):
    """
    Full product serializer for inventory list, detail, create, and update.

    Category auto-create:
      Pass either `category` (UUID) or `category_name` (string).
      When `category_name` is supplied, the category is found
      case-insensitively or created if it does not exist.
      `category_name` takes precedence over `category` when both are given.
    """

    # Read-only computed fields from model properties
    margin_pct    = serializers.FloatField(read_only=True)
    stock_status  = serializers.CharField(read_only=True)
    days_of_stock = serializers.IntegerField(read_only=True, allow_null=True)

    # Embedded display names (avoids extra round-trips from the frontend)
    category_name  = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    supplier_name  = serializers.CharField(source="supplier.name", read_only=True, allow_null=True)

    # Absolute URL for the product image (null when no image uploaded)
    image_url = serializers.SerializerMethodField()

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url

    # Write-only — accepts a category name and auto-creates when needed
    category_name_input = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text=(
            "Category name. If this category does not exist it will be created "
            "automatically. Overrides `category` (UUID) when supplied."
        ),
    )

    class Meta:
        model = Product
        fields = [
            # Identity
            "id", "store", "name", "sku", "barcode",

            # Classification
            "category", "category_name", "category_name_input",
            "supplier", "supplier_name",
            "unit", "color",

            # Image
            "image", "image_url",

            # Pricing
            "price", "cost", "margin_pct",

            # Stock
            "stock", "min_stock", "max_stock",
            "weekly_sold", "last_restock_at",

            # Computed
            "stock_status", "days_of_stock",

            # Meta
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "margin_pct", "stock_status", "days_of_stock",
            "image_url", "created_at", "updated_at",
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Selling price must be greater than zero.")
        return value

    def validate_cost(self, value):
        if value <= 0:
            raise serializers.ValidationError("Cost must be greater than zero.")
        return value

    def validate(self, attrs):
        # ── Category auto-create ──────────────────────────────────────────────
        # Pull out the write-only input field before saving
        category_name_input = attrs.pop("category_name_input", None)

        if category_name_input and category_name_input.strip():
            name = category_name_input.strip()
            # Case-insensitive lookup, create if not found
            cat = Category.objects.filter(name__iexact=name).first()
            if not cat:
                cat = Category.objects.create(name=name)
            attrs["category"] = cat

        # ── Margin guard ──────────────────────────────────────────────────────
        price = attrs.get("price", getattr(self.instance, "price", 0))
        cost  = attrs.get("cost",  getattr(self.instance, "cost",  0))
        if cost and price and cost >= price:
            raise serializers.ValidationError({
                "cost": "Cost must be less than the selling price."
            })

        return attrs


# ── Stock Adjustment ──────────────────────────────────────────────────────────

class StockAdjustmentSerializer(serializers.ModelSerializer):
    product_name      = serializers.CharField(source="product.name", read_only=True)
    product_sku       = serializers.CharField(source="product.sku",  read_only=True)
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "product", "product_name", "product_sku",
            "adjustment_type",
            "quantity_change", "quantity_before", "quantity_after",
            "reference", "note",
            "performed_by", "performed_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.get_full_name() or obj.performed_by.username
        return "System"


class ManualStockAdjustmentSerializer(serializers.Serializer):
    quantity_change = serializers.IntegerField(
        help_text="Units to add (+) or remove (-). Cannot be 0.",
    )
    note = serializers.CharField(
        max_length=500,
        help_text="Reason for this manual adjustment (required).",
    )

    def validate_quantity_change(self, value):
        if value == 0:
            raise serializers.ValidationError("Quantity change cannot be zero.")
        return value

"""
apps/accounts/api/serializers.py

Serializers for user accounts, organisations, and stores.

Each serializer converts a Django model instance to/from JSON.
We follow a consistent pattern:
  - *Serializer      → full read/write (create + update)
  - *ReadSerializer  → read-only, often includes computed fields
  - *WriteSerializer → write-only, for create/update with validated input
"""

from django.contrib.auth.password_validation import validate_password
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers

from ..models import AICredit, Organisation, Store, User


# ── Organisation ──────────────────────────────────────────────────────────────

class OrganisationSerializer(serializers.ModelSerializer):
    """
    Full serialiser for Organisation.
    Used when returning org details to the frontend.
    """

    # Include store count as a computed field
    store_count = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = [
            "id", "name", "legal_name", "tin",
            "country", "currency", "plan",
            "ai_credits_monthly", "trial_ends_at",
            "store_count", "created_at", "updated_at",
        ]
        # Never expose the UUID id in writable form — it's auto-generated
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_store_count(self, obj):
        """Number of active stores in this organisation."""
        return obj.stores.filter(is_active=True).count()


# ── Store ─────────────────────────────────────────────────────────────────────

class StoreSerializer(serializers.ModelSerializer):
    """
    Full serialiser for Store.
    Used in the store switcher and store management pages.
    """

    # Include the organisation name for display
    organisation_name = serializers.CharField(
        source="organisation.name",
        read_only=True,
    )

    # Include staff count
    staff_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id", "organisation", "organisation_name",
            "name", "code", "address", "area", "phone",
            "till_count", "is_active",
            "staff_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_staff_count(self, obj):
        """Number of active staff members at this store."""
        return obj.staff.filter(is_active=True).count()


class StoreMinimalSerializer(serializers.ModelSerializer):
    """
    Minimal store representation — used when embedding store in other serialisers.
    Keeps responses lean (e.g. in User serialiser).
    """

    class Meta:
        model = Store
        fields = ["id", "name", "area"]


# ── User ──────────────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    """
    Read serialiser for User — returned when getting user details.
    Includes computed initials, full_name, and performance stats.
    Stats are computed per-object; for list views use the annotated queryset
    via UserViewSet which annotates sales_today / txns_today efficiently.
    """

    full_name  = serializers.CharField(read_only=True)
    initials   = serializers.CharField(read_only=True)
    store_detail = StoreMinimalSerializer(source="store", read_only=True)

    # Performance stats — populated from queryset annotations when available,
    # or computed on demand for detail views.
    sales_today  = serializers.SerializerMethodField()
    total_sales  = serializers.SerializerMethodField()
    avg_ticket   = serializers.SerializerMethodField()
    txns_today   = serializers.SerializerMethodField()
    txns_total   = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email",
            "first_name", "last_name", "full_name", "initials",
            "phone", "role", "avatar_hue",
            # Staff schedule & status
            "shift", "employment_status", "pin",
            # Per-staff permissions
            "can_refund", "can_discount", "can_view_reports",
            "store", "store_detail",
            "is_active", "date_joined", "last_login",
            "created_at", "updated_at",
            # Performance stats (computed)
            "sales_today", "total_sales", "avg_ticket",
            "txns_today", "txns_total",
        ]
        read_only_fields = [
            "id", "full_name", "initials", "date_joined",
            "last_login", "created_at", "updated_at",
            "sales_today", "total_sales", "avg_ticket",
            "txns_today", "txns_total",
        ]

    def _txn_qs(self, obj):
        """Return the Transaction queryset for this user, or None if unavailable."""
        try:
            return obj.transactions.all()
        except Exception:
            return None

    def get_sales_today(self, obj):
        # Use queryset annotation if available (list view), else compute inline
        if hasattr(obj, "_sales_today"):
            return obj._sales_today or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        today = timezone.now().date()
        result = qs.filter(created_at__date=today, status="paid").aggregate(
            t=Sum("total")
        )
        return result["t"] or 0

    def get_total_sales(self, obj):
        if hasattr(obj, "_total_sales"):
            return obj._total_sales or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        result = qs.filter(status="paid").aggregate(t=Sum("total"))
        return result["t"] or 0

    def get_avg_ticket(self, obj):
        if hasattr(obj, "_avg_ticket"):
            return round(obj._avg_ticket or 0)
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        result = qs.filter(status="paid").aggregate(a=Avg("total"))
        return round(result["a"] or 0)

    def get_txns_today(self, obj):
        if hasattr(obj, "_txns_today"):
            return obj._txns_today or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        today = timezone.now().date()
        return qs.filter(created_at__date=today).count()

    def get_txns_total(self, obj):
        if hasattr(obj, "_txns_total"):
            return obj._txns_total or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        return qs.count()


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Write serialiser for creating a new staff member.
    Validates password strength and hashes it before saving.
    Permissions default by role if not supplied.
    """

    password         = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            "username", "email", "password", "password_confirm",
            "first_name", "last_name", "phone", "role", "store",
            "avatar_hue", "shift", "employment_status", "pin",
            "can_refund", "can_discount", "can_view_reports",
        ]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        # Default permissions by role if not explicitly provided
        role = validated_data.get("role", User.ROLE_CASHIER)
        if "can_refund" not in validated_data:
            validated_data["can_refund"] = role in (User.ROLE_ADMIN, User.ROLE_MANAGER)
        if "can_discount" not in validated_data:
            validated_data["can_discount"] = True
        if "can_view_reports" not in validated_data:
            validated_data["can_view_reports"] = role in (User.ROLE_ADMIN, User.ROLE_MANAGER)
        return User.objects.create_user(**validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Write serialiser for updating a staff member's profile (excluding password).
    Includes all staff-management fields the UI can modify.
    """

    class Meta:
        model = User
        fields = [
            "email", "first_name", "last_name",
            "phone", "role", "store", "avatar_hue",
            "shift", "employment_status", "pin",
            "can_refund", "can_discount", "can_view_reports",
            "is_active",
        ]


class StaffStatsSerializer(serializers.Serializer):
    """
    Response body for GET /api/v1/accounts/users/{id}/stats/
    Performance metrics for a single staff member.
    """

    user_id      = serializers.IntegerField()
    full_name    = serializers.CharField()
    sales_today  = serializers.IntegerField()
    total_sales  = serializers.IntegerField()
    avg_ticket   = serializers.IntegerField()
    txns_today   = serializers.IntegerField()
    txns_total   = serializers.IntegerField()


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serialiser for the change-password endpoint.
    Requires the user to supply their current password before changing.
    """

    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
    )
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs.pop("new_password_confirm"):
            raise serializers.ValidationError({
                "new_password_confirm": "Passwords do not match."
            })
        return attrs


# ── AI Credits ────────────────────────────────────────────────────────────────

class AICreditSerializer(serializers.ModelSerializer):
    """
    Serialiser for AI credit usage — shown in sidenav footer.
    """

    # Computed from model properties
    remaining = serializers.IntegerField(read_only=True)
    percentage_used = serializers.FloatField(read_only=True)

    class Meta:
        model = AICredit
        fields = [
            "id", "year", "month",
            "used", "allocated", "remaining", "percentage_used",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

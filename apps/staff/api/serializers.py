"""
apps/staff/api/serializers.py

Serializers for the staff management API.

StaffSerializer           → full read (list + detail), includes computed stats
StaffCreateSerializer     → POST /api/v1/staff/ (create new staff member)
StaffUpdateSerializer     → PATCH /api/v1/staff/{id}/ (update profile fields)
ShiftUpdateSerializer     → PATCH /api/v1/staff/{id}/shift/
PermissionsUpdateSerializer → PATCH /api/v1/staff/{id}/permissions/
StaffStatsSerializer      → GET /api/v1/staff/{id}/stats/
StaffActivitySerializer   → entries inside GET /api/v1/staff/{id}/activity/
StaffKPISerializer        → GET /api/v1/staff/kpis/
"""

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User


# ── Helpers ───────────────────────────────────────────────────────────────────

class StoreMinimalSerializer(serializers.Serializer):
    """Lean store representation embedded in staff responses."""
    id   = serializers.UUIDField()
    name = serializers.CharField()
    area = serializers.CharField()


# ── Main read serializer ──────────────────────────────────────────────────────

class StaffSerializer(serializers.ModelSerializer):
    """
    Full read representation of a staff member.

    Computed stats (sales_today, total_sales, etc.) are populated from
    queryset annotations in list views (single JOIN, no N+1), or from
    the _sales_today / _txns_today etc. attributes when set directly.
    Detail view computes them via services.get_staff_stats().
    """

    full_name    = serializers.CharField(read_only=True)
    initials     = serializers.CharField(read_only=True)
    store_detail = StoreMinimalSerializer(source="store", read_only=True)
    store_name   = serializers.CharField(source="store.name", read_only=True, default=None)

    # Human-readable shift label
    shift_display = serializers.SerializerMethodField()

    # Performance stats — populated from annotations or direct attrs
    sales_today  = serializers.SerializerMethodField()
    txns_today   = serializers.SerializerMethodField()
    total_sales  = serializers.SerializerMethodField()
    avg_ticket   = serializers.SerializerMethodField()
    txns_total   = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email",
            "first_name", "last_name", "full_name", "initials",
            "phone", "role", "avatar_hue",
            "shift", "shift_display", "employment_status",
            "can_refund", "can_discount", "can_view_reports",
            "pin",
            "store", "store_name", "store_detail",
            "is_active", "date_joined", "last_login",
            "created_at", "updated_at",
            # computed
            "sales_today", "txns_today", "total_sales", "avg_ticket", "txns_total",
        ]
        read_only_fields = [
            "id", "full_name", "initials", "date_joined",
            "last_login", "created_at", "updated_at",
            "shift_display",
            "sales_today", "txns_today", "total_sales", "avg_ticket", "txns_total",
        ]

    # Shift display labels matching the UI
    SHIFT_LABELS = {
        User.SHIFT_MORNING:  "Morning (7am–2pm)",
        User.SHIFT_EVENING:  "Evening (2pm–9pm)",
        User.SHIFT_FULL_DAY: "Full day (7am–7pm)",
        User.SHIFT_WEEKEND:  "Weekend (Sat–Sun)",
    }

    def get_shift_display(self, obj):
        return self.SHIFT_LABELS.get(obj.shift, obj.shift)

    def _stat(self, obj, attr, annotation):
        """Read from queryset annotation if present, else from direct attribute."""
        if hasattr(obj, annotation):
            return getattr(obj, annotation) or 0
        return 0

    def get_sales_today(self, obj):
        return self._stat(obj, "sales_today", "_sales_today")

    def get_txns_today(self, obj):
        return self._stat(obj, "txns_today", "_txns_today")

    def get_total_sales(self, obj):
        return self._stat(obj, "total_sales", "_total_sales")

    def get_avg_ticket(self, obj):
        v = self._stat(obj, "avg_ticket", "_avg_ticket")
        return round(v)

    def get_txns_total(self, obj):
        return self._stat(obj, "txns_total", "_txns_total")


# ── Write serializers ─────────────────────────────────────────────────────────

class StaffCreateSerializer(serializers.ModelSerializer):
    """
    Create a new staff member (POST /api/v1/staff/).

    The password is required for the Django User model. If you want to
    allow PIN-only access you still need a system password — the view
    auto-generates one if omitted.
    """

    password         = serializers.CharField(write_only=True, required=False, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "username", "email", "password", "password_confirm",
            "first_name", "last_name", "phone",
            "role", "shift", "employment_status",
            "can_refund", "can_discount", "can_view_reports",
            "avatar_hue", "pin",
        ]

    def validate(self, attrs):
        password         = attrs.get("password")
        password_confirm = attrs.pop("password_confirm", None)
        if password and password_confirm and password != password_confirm:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def validate_pin(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError("PIN must be numeric.")
        if value and len(value) != 4:
            raise serializers.ValidationError("PIN must be exactly 4 digits.")
        return value

    def create(self, validated_data):
        import secrets

        role = validated_data.get("role", User.ROLE_STAFF)

        # Default permissions by role if not supplied
        validated_data.setdefault(
            "can_refund", role in (User.ROLE_ADMIN, User.ROLE_OWNER)
        )
        validated_data.setdefault("can_discount", True)
        validated_data.setdefault(
            "can_view_reports", role in (User.ROLE_ADMIN, User.ROLE_OWNER)
        )

        # Auto-generate a strong password if none provided
        password = validated_data.pop("password", None) or secrets.token_urlsafe(16)

        return User.objects.create_user(password=password, **validated_data)


class StaffUpdateSerializer(serializers.ModelSerializer):
    """
    Update a staff member's profile (PATCH /api/v1/staff/{id}/).
    All fields are optional (partial update).
    """

    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "email", "phone",
            "role", "shift", "employment_status",
            "can_refund", "can_discount", "can_view_reports",
            "avatar_hue", "pin", "is_active",
        ]

    def validate_pin(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError("PIN must be numeric.")
        if value and len(value) != 4:
            raise serializers.ValidationError("PIN must be exactly 4 digits.")
        return value


class ShiftUpdateSerializer(serializers.ModelSerializer):
    """
    Patch only shift + employment_status (PATCH /api/v1/staff/{id}/shift/).
    """

    class Meta:
        model = User
        fields = ["shift", "employment_status"]


class PermissionsUpdateSerializer(serializers.ModelSerializer):
    """
    Patch only POS permissions (PATCH /api/v1/staff/{id}/permissions/).
    """

    class Meta:
        model = User
        fields = ["can_refund", "can_discount", "can_view_reports"]


# ── Stats / activity response serializers ────────────────────────────────────

class StaffStatsSerializer(serializers.Serializer):
    """Response body for GET /api/v1/staff/{id}/stats/"""
    user_id          = serializers.IntegerField()
    full_name        = serializers.CharField()
    role             = serializers.CharField()
    employment_status = serializers.CharField()
    shift            = serializers.CharField()
    sales_today      = serializers.IntegerField()
    txns_today       = serializers.IntegerField()
    total_sales      = serializers.IntegerField()
    avg_ticket       = serializers.IntegerField()
    txns_total       = serializers.IntegerField()
    sales_this_month = serializers.IntegerField()
    txns_this_month  = serializers.IntegerField()


class StaffActivityEntrySerializer(serializers.Serializer):
    """One transaction activity entry in GET /api/v1/staff/{id}/activity/"""
    id         = serializers.CharField()
    time       = serializers.CharField()
    type       = serializers.CharField()           # 'sale' | 'refund'
    amount     = serializers.IntegerField(required=False, allow_null=True)
    items      = serializers.IntegerField(required=False, allow_null=True)
    method     = serializers.CharField(required=False, allow_null=True)
    txn_number = serializers.CharField(required=False, allow_null=True)
    status     = serializers.CharField(required=False, allow_null=True)


class StaffKPISerializer(serializers.Serializer):
    """Response body for GET /api/v1/staff/kpis/"""
    total_staff       = serializers.IntegerField()
    active            = serializers.IntegerField()
    on_leave          = serializers.IntegerField()
    inactive          = serializers.IntegerField()
    on_shift_today    = serializers.IntegerField()
    on_duty           = serializers.IntegerField()
    sales_today       = serializers.IntegerField()
    txns_today        = serializers.IntegerField()
    sales_this_month  = serializers.IntegerField()
    total_sales_today = serializers.IntegerField()
    avg_ticket_today  = serializers.IntegerField()
    top_cashier       = serializers.CharField(allow_null=True)

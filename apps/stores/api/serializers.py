"""
apps/stores/api/serializers.py

Serializers for the stores management page.

  StoreListSerializer   — card grid (includes live KPIs + week sparkline)
  StoreDetailSerializer — detail page (extends list + week breakdown + staff roster)
  StoreWriteSerializer  — create / partial update
  OrgStatsSerializer    — KPI header strip (plain Serializer, data from services)
"""

from rest_framework import serializers

from apps.accounts.models import Store

from ..services import (
    get_staff_on_duty_count,
    get_staff_roster,
    get_store_manager,
    get_store_today_kpis,
    get_store_week_breakdown,
    get_store_week_data,
)


class StoreListSerializer(serializers.ModelSerializer):
    """
    Store card — includes live KPIs computed from DailySummary.
    Used for GET /api/v1/stores/ (the store grid).
    """

    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    staff_count       = serializers.SerializerMethodField()
    manager_name      = serializers.SerializerMethodField()
    today_revenue     = serializers.SerializerMethodField()
    today_txns        = serializers.SerializerMethodField()
    staff_on_duty     = serializers.SerializerMethodField()
    week_data         = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            # Identity
            "id", "organisation", "organisation_name",
            "name", "code", "area", "address", "phone", "email",
            "color", "open_hours", "till_count",

            # Status
            "status", "is_active",

            # Staff
            "manager_name", "staff_count", "staff_on_duty",

            # Live KPIs (from DailySummary)
            "today_revenue", "today_txns",

            # Sparkline (current ISO week)
            "week_data",

            # Timestamps
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_staff_count(self, obj):
        return obj.staff.filter(is_active=True).count()

    def get_manager_name(self, obj):
        manager = get_store_manager(obj)
        return manager.get_full_name() or manager.username if manager else None

    def get_today_revenue(self, obj):
        return get_store_today_kpis(obj)["today_revenue"]

    def get_today_txns(self, obj):
        return get_store_today_kpis(obj)["today_txns"]

    def get_staff_on_duty(self, obj):
        return get_staff_on_duty_count(obj)

    def get_week_data(self, obj):
        return get_store_week_data(obj)


class StoreDetailSerializer(StoreListSerializer):
    """
    Full store detail — extends StoreListSerializer with the week chart
    and the staff roster for the detail page tabs.
    """

    week_breakdown = serializers.SerializerMethodField()
    staff_roster   = serializers.SerializerMethodField()

    class Meta(StoreListSerializer.Meta):
        fields = StoreListSerializer.Meta.fields + [
            "week_breakdown",
            "staff_roster",
        ]

    def get_week_breakdown(self, obj):
        return get_store_week_breakdown(obj)

    def get_staff_roster(self, obj):
        return get_staff_roster(obj)


class StoreWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for create + partial update.

    NOTE: is_active is intentionally excluded — new stores are always active.
    Deactivation happens via the DELETE endpoint (soft-delete).
    Including a BooleanField with no value in multipart/form-data causes DRF
    to default it to False, which would create inactive stores unexpectedly.
    """

    class Meta:
        model = Store
        fields = [
            "organisation",
            "name", "code", "area", "address",
            "phone", "email", "open_hours", "color",
            "till_count", "status",
        ]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Store name cannot be blank.")
        return value.strip()


class OrgStatsSerializer(serializers.Serializer):
    """
    Read-only KPI header strip for the stores list page.
    Data is produced by services.get_org_stats() — no model backing.
    """

    total_stores  = serializers.IntegerField()
    open_count    = serializers.IntegerField()
    closed_count  = serializers.IntegerField()
    paused_count  = serializers.IntegerField()
    total_revenue = serializers.IntegerField()
    total_txns    = serializers.IntegerField()
    staff_on_duty = serializers.IntegerField()

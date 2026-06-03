"""
apps/subscriptions/api/serializers.py

Serializers for subscription plans and subscriptions.
"""

from rest_framework import serializers

from ..models import Subscription, SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Public serializer for pricing plans.
    Shown on the registration/upgrade screen.
    """

    total_price            = serializers.IntegerField(read_only=True)
    extra_store_price_total = serializers.IntegerField(read_only=True)

    class Meta:
        model  = SubscriptionPlan
        fields = [
            "id", "name", "slug", "description",
            "price_per_month", "duration_months", "total_price",
            "included_stores", "extra_store_price_per_month", "extra_store_price_total",
            "is_active", "sort_order",
        ]
        read_only_fields = ["id"]


class SubscriptionSerializer(serializers.ModelSerializer):
    """
    Full subscription detail — returned to owners and admins.
    """

    plan_detail          = SubscriptionPlanSerializer(source="plan", read_only=True)
    organisation_name    = serializers.CharField(source="organisation.name", read_only=True)
    is_active_now        = serializers.BooleanField(read_only=True)
    days_remaining       = serializers.IntegerField(read_only=True)
    max_stores_allowed   = serializers.IntegerField(read_only=True)
    total_amount_due     = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Subscription
        fields = [
            "id", "organisation", "organisation_name",
            "plan", "plan_detail", "status",
            "start_date", "end_date", "is_trial", "trial_fee",
            "extra_stores",
            "amount_paid", "payment_reference", "payment_date",
            "is_active_now", "days_remaining",
            "max_stores_allowed", "total_amount_due",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organisation", "created_at", "updated_at",
            "is_active_now", "days_remaining", "max_stores_allowed", "total_amount_due",
        ]


class SubscriptionActivateSerializer(serializers.Serializer):
    """
    Used by Cameltech admins to confirm a payment and activate a subscription.
    POST /api/v1/subscriptions/{id}/activate/
    """

    status            = serializers.ChoiceField(choices=[Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIAL])
    payment_reference = serializers.CharField(required=False, allow_blank=True)
    payment_date      = serializers.DateField(required=False, allow_null=True)
    amount_paid       = serializers.IntegerField(required=False, min_value=0)
    notes             = serializers.CharField(required=False, allow_blank=True)


class ExtraStoreSerializer(serializers.Serializer):
    """
    Used by Cameltech admins to add extra stores to a subscription.
    PATCH /api/v1/subscriptions/{id}/extra-stores/
    """

    extra_stores = serializers.IntegerField(min_value=0)

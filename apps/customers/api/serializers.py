"""
apps/customers/api/serializers.py

Serializers for the Customer model.

Covers:
  - CustomerSerializer       → full read (detail view)
  - CustomerListSerializer   → lightweight read (list view, no nested data)
  - CustomerCreateSerializer → write (create a new customer)
  - CustomerUpdateSerializer → write (PATCH contact info, segment, notes)

Key design note:
  total_spent, last_visit, avg_ticket, open_credit are read-only cache fields.
  They are updated by signals when transactions are completed/refunded, and when
  credit payments are recorded. Staff cannot set them manually via the API.
"""

from rest_framework import serializers

from ..models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    """
    Full read serialiser for a single customer.
    Used in the /customers/[id] detail view.

    Includes all fields including cached stats and computed properties.
    """

    # Computed properties from the model
    initials         = serializers.CharField(read_only=True)
    has_open_credit  = serializers.BooleanField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            # Identity
            "id", "store",
            "name", "phone", "email",

            # Display
            "avatar_hue", "initials", "segment",

            # Stats (read-only cached values)
            "total_spent", "last_visit", "avg_ticket",
            "open_credit", "has_open_credit",
            "credit_limit",

            # Meta
            "notes", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "store",
            "initials", "has_open_credit",
            "total_spent", "last_visit", "avg_ticket", "open_credit",
            "created_at", "updated_at",
        ]


class CustomerListSerializer(serializers.ModelSerializer):
    """
    Lightweight serialiser for the customer list view (/customers page).
    Omits notes and some metadata to keep list responses lean.
    """

    initials        = serializers.CharField(read_only=True)
    has_open_credit = serializers.BooleanField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id", "name", "phone",
            "avatar_hue", "initials", "segment",
            "total_spent", "last_visit", "avg_ticket",
            "open_credit", "has_open_credit", "credit_limit",
            "is_active", "created_at",
        ]


class CustomerCreateSerializer(serializers.ModelSerializer):
    """
    Write serialiser for POST /customers/.

    store is injected from request.user.store in the view, not sent by the client.
    The client only provides name, phone, email (optional), segment, avatar_hue, notes.
    """

    class Meta:
        model = Customer
        fields = [
            "name", "phone", "email",
            "segment", "avatar_hue", "notes", "credit_limit",
        ]

    def validate_phone(self, value):
        """
        Phone numbers should start with + and contain only digits/spaces.
        Tanzania numbers: +255 7XX XXX XXX
        We don't strictly enforce format (too many edge cases), just clean whitespace.
        """
        # Trim but preserve format
        return value.strip()

    def validate(self, attrs):
        """
        Check that phone is unique within the store before creating.
        The store is injected by the view into context.
        """
        phone = attrs.get("phone", "")
        store = self.context.get("store")

        if phone and store:
            if Customer.objects.filter(store=store, phone=phone, is_active=True).exists():
                raise serializers.ValidationError({
                    "phone": "A customer with this phone number already exists in this store."
                })
        return attrs


class CustomerUpdateSerializer(serializers.ModelSerializer):
    """
    Write serialiser for PATCH /customers/{id}/.
    Allows updating contact info, segment, and notes — not stats.
    """

    class Meta:
        model = Customer
        fields = [
            "name", "phone", "email",
            "segment", "avatar_hue", "notes", "is_active", "credit_limit",
        ]


class CustomerMinimalSerializer(serializers.ModelSerializer):
    """
    Minimal serialiser used as nested representation in other apps.
    E.g., shown in Transaction detail and CreditTab.
    """

    initials = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "avatar_hue", "initials", "segment"]


class SendCustomerSmsSerializer(serializers.Serializer):
    """Input for POST /customers/{id}/send-sms/ — an ad-hoc SMS, unrelated to credit."""

    message = serializers.CharField(max_length=640, trim_whitespace=True)

"""
apps/accounts/api/serializers.py

Serializers for user accounts, organisations, stores, and registration.

Key serializers:
  RegistrationSerializer  → atomic account creation (org + store + owner + trial)
  PhoneLoginSerializer    → phone + password → JWT tokens + user data
  UserSerializer          → full read serializer (returned on login, profile, etc.)
  UserCreateSerializer    → owner creates a staff member
  UserUpdateSerializer    → profile/staff updates
"""

import random
from datetime import date, timedelta
import uuid

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tanzania import (
    BUSINESS_TYPE_CHOICES,
    REGION_CHOICES,
    TANZANIA_REGIONS,
    seed_categories_for_store,
)

from ..models import AICredit, Organisation, Store, User


# ── Organisation ──────────────────────────────────────────────────────────────

class OrganisationSerializer(serializers.ModelSerializer):

    store_count = serializers.SerializerMethodField()

    class Meta:
        model  = Organisation
        fields = [
            "id", "name", "legal_name", "tin",
            "business_type", "region",
            "country", "currency", "plan", "max_stores",
            "ai_credits_monthly", "trial_ends_at",
            "store_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "max_stores"]

    def get_store_count(self, obj):
        return obj.stores.filter(is_active=True).count()


# ── Store ─────────────────────────────────────────────────────────────────────

class StoreSerializer(serializers.ModelSerializer):

    organisation_name = serializers.CharField(source="organisation.name", read_only=True)
    staff_count       = serializers.SerializerMethodField()

    class Meta:
        model  = Store
        fields = [
            "id", "organisation", "organisation_name",
            "name", "code", "address", "area", "phone",
            "till_count", "is_active", "is_main_store",
            "vat_enabled",
            "staff_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_staff_count(self, obj):
        return obj.staff.filter(is_active=True).count()


class StoreMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Store
        fields = ["id", "name", "area"]


# ── User ──────────────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    """Read serializer — returned on login, /me, user detail, and staff list."""

    full_name    = serializers.CharField(read_only=True)
    initials     = serializers.CharField(read_only=True)
    store_detail = StoreMinimalSerializer(source="store", read_only=True)

    # Verification status
    is_phone_verified = serializers.BooleanField(read_only=True)
    is_email_verified = serializers.BooleanField(read_only=True)

    # Performance stats
    sales_today  = serializers.SerializerMethodField()
    total_sales  = serializers.SerializerMethodField()
    avg_ticket   = serializers.SerializerMethodField()
    txns_today   = serializers.SerializerMethodField()
    txns_total   = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            "id", "phone", "email",
            "first_name", "last_name", "full_name", "initials",
            "role", "avatar_hue",
            "is_phone_verified", "is_email_verified",
            "shift", "employment_status", "pin",
            "can_refund", "can_discount", "can_view_reports",
            "store", "store_detail",
            "organisation",
            "is_active", "date_joined", "last_login",
            "created_at", "updated_at",
            "sales_today", "total_sales", "avg_ticket",
            "txns_today", "txns_total",
        ]
        read_only_fields = [
            "id", "full_name", "initials", "date_joined",
            "last_login", "created_at", "updated_at",
            "is_phone_verified", "is_email_verified",
            "sales_today", "total_sales", "avg_ticket",
            "txns_today", "txns_total",
        ]

    def _txn_qs(self, obj):
        try:
            return obj.transactions.all()
        except Exception:
            return None

    def get_sales_today(self, obj):
        if hasattr(obj, "_sales_today"):
            return obj._sales_today or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        today = timezone.now().date()
        return qs.filter(created_at__date=today, status="paid").aggregate(t=Sum("total"))["t"] or 0

    def get_total_sales(self, obj):
        if hasattr(obj, "_total_sales"):
            return obj._total_sales or 0
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        return qs.filter(status="paid").aggregate(t=Sum("total"))["t"] or 0

    def get_avg_ticket(self, obj):
        if hasattr(obj, "_avg_ticket"):
            return round(obj._avg_ticket or 0)
        qs = self._txn_qs(obj)
        if qs is None:
            return 0
        return round(qs.filter(status="paid").aggregate(a=Avg("total"))["a"] or 0)

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


# ── Registration ──────────────────────────────────────────────────────────────

class RegistrationSerializer(serializers.Serializer):
    """
    Owner self-registration.

    Atomically creates:
      1. Organisation  (name = main_shop_name, business_type, region)
      2. Store         (main store, is_main_store=True)
      3. User          (role=owner, phone, name, password)
      4. Subscription  (trial: 10,000 TZS, 7 days, status=pending_payment)

    Then seeds pre-configured categories for the business type.

    Returns: { user, organisation, subscription, access, refresh }
    """

    # ── Owner personal details ─────────────────────────────────────────────────
    full_name        = serializers.CharField(max_length=200)
    phone            = serializers.RegexField(
        r"^\d{10}$",
        error_messages={"invalid": "Phone must be exactly 10 digits (e.g. 0712345678)."},
    )
    password         = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
    email            = serializers.EmailField(required=False, allow_blank=True, default=None)

    # ── Business details ────────────────────────────────────────────────────────
    main_shop_name = serializers.CharField(
        max_length=200,
        help_text="Name of the main shop (becomes the Organisation name and first Store name).",
    )
    business_type  = serializers.ChoiceField(
        choices=[c[0] for c in BUSINESS_TYPE_CHOICES],
    )
    region         = serializers.ChoiceField(choices=TANZANIA_REGIONS)

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email address is already registered.")
        return value or None

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.subscriptions.models import Subscription

        phone          = validated_data["phone"]
        full_name      = validated_data["full_name"]
        main_shop_name = validated_data["main_shop_name"]
        business_type  = validated_data["business_type"]
        region         = validated_data["region"]
        email          = validated_data.get("email")

        # Split full_name into first + last
        name_parts = full_name.strip().split(None, 1)
        first_name = name_parts[0] or ""
        last_name  = name_parts[1] if len(name_parts) > 1 else (first_name or "")

        # 1. Create Organisation
        org = Organisation.objects.create(
            name          = main_shop_name,
            business_type = business_type,
            region        = region,
            max_stores    = 3,
        )

        # 2. Create main Store
        store = Store.objects.create(
            organisation  = org,
            name          = main_shop_name,
            is_main_store = True,
            color         = f"#{random.randint(0, 0xFFFFFF):06x}",
        )

        # 3. Create owner User
        user = User.objects.create_user(
            username   = phone,        # username = phone (kept in sync by model.save)
            phone      = phone,
            email      = email,
            first_name = first_name,
            last_name  = last_name,
            password   = validated_data["password"],
            role       = User.ROLE_OWNER,
            organisation = org,
            store        = store,
            avatar_hue   = random.randint(0, 359),
            can_refund       = True,
            can_discount     = True,
            can_view_reports = True,
        )

        # 4. Create trial Subscription (pending payment confirmation)
        now   = timezone.now()
        today = now.date()
        trial = Subscription.objects.create(
            organisation    = org,
            status          = Subscription.STATUS_PENDING,
            start_date      = today,
            end_date        = today + timedelta(days=7),
            is_trial        = True,
            trial_fee       = 10000,
            extra_stores    = 0,
        )

        # 5. Set trial_ends_at on org for fast subscription checks
        org.trial_ends_at = now + timedelta(days=7)
        org.save(update_fields=["trial_ends_at", "updated_at"])

        # 6. Seed pre-configured categories for this business type
        seed_categories_for_store(store, business_type)

        # 7. Generate JWT tokens so user is auto-logged in after registration
        refresh = RefreshToken.for_user(user)

        # 8. Send welcome + email confirmation (fire-and-forget; never block registration)
        if user.email:
            try:
                from apps.notifications.emails import send_welcome_email
                send_welcome_email(user)
            except Exception:
                pass  # Never fail registration because of email

        return {
            "user":         user,
            "organisation": org,
            "store":        store,
            "subscription": trial,
            "access":       str(refresh.access_token),
            "refresh":      str(refresh),
        }


# ── Phone Login ───────────────────────────────────────────────────────────────

class PhoneLoginSerializer(serializers.Serializer):
    """
    Authenticate with phone number + password.
    Returns JWT tokens + full user profile + subscription status.

    POST /api/v1/auth/login/
      { "phone": "0712345678", "password": "..." }
    """

    phone    = serializers.RegexField(
        r"^\d{10}$",
        error_messages={"invalid": "Enter a valid 10-digit phone number."},
    )
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        phone    = attrs["phone"]
        password = attrs["password"]

        try:
            user = User.objects.select_related("store", "store__organisation", "organisation").get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError({"phone": "Invalid phone number or password."})

        if not user.check_password(password):
            raise serializers.ValidationError({"password": "Invalid phone number or password."})

        if not user.is_active:
            raise serializers.ValidationError({"phone": "This account has been deactivated."})

        attrs["user"] = user
        return attrs


# ── Staff management ──────────────────────────────────────────────────────────

class UserCreateSerializer(serializers.ModelSerializer):
    """
    Owner creates a new staff member for their store.
    Staff get role=staff and are linked to the owner's store.
    """

    password         = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model  = User
        fields = [
            "phone", "email", "password", "password_confirm",
            "first_name", "last_name", "role", "store",
            "avatar_hue", "shift", "employment_status", "pin",
            "can_refund", "can_discount", "can_view_reports",
        ]

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value or None

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        # Staff can only be assigned role=staff; owners use registration flow
        if attrs.get("role") not in (User.ROLE_STAFF, User.ROLE_OWNER):
            attrs["role"] = User.ROLE_STAFF
        return attrs

    def create(self, validated_data):
        role = validated_data.get("role", User.ROLE_STAFF)
        if "can_refund" not in validated_data:
            validated_data["can_refund"] = role == User.ROLE_OWNER
        if "can_view_reports" not in validated_data:
            validated_data["can_view_reports"] = role == User.ROLE_OWNER
        phone = validated_data["phone"]
        validated_data.setdefault("username", phone)
        return User.objects.create_user(**validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    """Update staff profile or permissions. No password change here."""

    class Meta:
        model  = User
        fields = [
            "email", "first_name", "last_name",
            "phone", "role", "store", "avatar_hue",
            "shift", "employment_status", "pin",
            "can_refund", "can_discount", "can_view_reports",
            "is_active",
        ]


class StaffStatsSerializer(serializers.Serializer):
    user_id      = serializers.IntegerField()
    full_name    = serializers.CharField()
    sales_today  = serializers.IntegerField()
    total_sales  = serializers.IntegerField()
    avg_ticket   = serializers.IntegerField()
    txns_today   = serializers.IntegerField()
    txns_total   = serializers.IntegerField()


class ChangePasswordSerializer(serializers.Serializer):
    old_password         = serializers.CharField(write_only=True, required=True)
    new_password         = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs.pop("new_password_confirm"):
            raise serializers.ValidationError({
                "new_password_confirm": "Passwords do not match."
            })
        return attrs


# ── AI Credits ────────────────────────────────────────────────────────────────

class AICreditSerializer(serializers.ModelSerializer):
    remaining        = serializers.IntegerField(read_only=True)
    percentage_used  = serializers.FloatField(read_only=True)

    class Meta:
        model  = AICredit
        fields = [
            "id", "year", "month",
            "used", "allocated", "remaining", "percentage_used",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ── Password Reset ──────────────────────────────────────────────────────────────

class ForgotPasswordRequestSerializer(serializers.Serializer):
    """
    POST /api/v1/auth/forgot-password/
    Request a password reset token for the given phone number.
    """
    phone = serializers.RegexField(
        r"^\d{10}$",
        error_messages={"invalid": "Enter a valid 10-digit phone number (e.g. 0712345678)."},
    )

    def validate_phone(self, value):
        # Check if user exists (for security, we don't reveal if a number is registered)
        # We still process the request but don't leak existence.
        return value


class SetNewPasswordSerializer(serializers.Serializer):
    """
    POST /api/v1/auth/reset-password/
    Confirm password reset with the token and set new password.
    """
    token       = serializers.UUIDField()
    new_password         = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        token = attrs["token"]
        try:
            user = User.objects.get(password_reset_token=token)
        except User.DoesNotExist:
            raise serializers.ValidationError({"token": "Invalid or expired reset token."})

        if user.password_reset_token_expires and user.password_reset_token_expires < timezone.now():
            raise serializers.ValidationError({"token": "Reset token has expired. Please request a new one."})

        if attrs["new_password"] != attrs.pop("new_password_confirm"):
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})

        attrs["user"] = user
        return attrs

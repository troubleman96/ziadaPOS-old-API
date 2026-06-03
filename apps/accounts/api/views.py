"""
apps/accounts/api/views.py

API views for accounts: registration, login, users, stores, organisations, AI credits.

Auth flow:
  POST /api/v1/auth/register/ → create account (org + store + owner + trial sub)
  POST /api/v1/auth/login/    → phone + password → JWT tokens + user profile
"""

import logging

from django.contrib.auth import update_session_auth_hash
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.permissions import IsOwner, IsStoreStaff, IsSystemAdmin
from apps.core.response import (
    created_response,
    error_response,
    success_response,
)

from ..models import AICredit, Organisation, Store, User
from .serializers import (
    AICreditSerializer,
    ChangePasswordSerializer,
    OrganisationSerializer,
    PhoneLoginSerializer,
    RegistrationSerializer,
    StaffStatsSerializer,
    StoreSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)


# ── Registration ──────────────────────────────────────────────────────────────

class RegisterView(APIView):
    """
    POST /api/v1/auth/register/

    Self-registration for new business owners.

    Required fields:
      full_name, phone (10 digits), password, confirm_password,
      main_shop_name, business_type, region

    Optional fields:
      email

    Response includes JWT tokens so the user is auto-logged in.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Registration failed. Please check the errors below.",
                errors=serializer.errors,
                status=400,
            )

        result = serializer.save()

        logger.info(
            "New owner registered: phone=%s org='%s'",
            result["user"].phone,
            result["organisation"].name,
        )

        return created_response(
            data={
                "user":         UserSerializer(result["user"]).data,
                "organisation": OrganisationSerializer(result["organisation"]).data,
                "subscription": {
                    "id":          str(result["subscription"].id),
                    "status":      result["subscription"].status,
                    "is_trial":    True,
                    "end_date":    str(result["subscription"].end_date),
                    "trial_fee":   result["subscription"].trial_fee,
                    "days_remaining": result["subscription"].days_remaining,
                },
                "access":       result["access"],
                "refresh":      result["refresh"],
            },
            message=(
                f"Welcome to Ziada! Your account has been created. "
                f"Please pay 10,000 TZS to activate your 7-day trial."
            ),
        )


# ── Login (phone + password) ──────────────────────────────────────────────────

class PhoneLoginView(APIView):
    """
    POST /api/v1/auth/login/

    Authenticates with phone number + password (replaces username-based login).

    Response:
      access, refresh     → JWT tokens
      user                → full user profile
      subscription        → current subscription status
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PhoneLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid credentials.",
                errors=serializer.errors,
                status=401,
            )

        user = serializer.validated_data["user"]

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        # Get subscription status
        org = user.get_organisation
        sub_data = None
        if org:
            sub = org.subscriptions.order_by("-created_at").first()
            if sub:
                sub_data = {
                    "id":             str(sub.id),
                    "status":         sub.status,
                    "is_trial":       sub.is_trial,
                    "is_active_now":  sub.is_active_now,
                    "days_remaining": sub.days_remaining,
                    "end_date":       str(sub.end_date),
                }

        logger.info("User login: phone=%s role=%s", user.phone, user.role)

        return success_response(
            data={
                "access":       str(refresh.access_token),
                "refresh":      str(refresh),
                "user":         UserSerializer(user).data,
                "subscription": sub_data,
            },
            message="Logged in successfully.",
        )


# ── Current User ("me") ───────────────────────────────────────────────────────

class MeView(APIView):
    """
    GET  /api/v1/accounts/me/  → return the currently logged-in user's profile
    PATCH /api/v1/accounts/me/ → update profile fields

    Response includes verification status so the frontend can show
    reminder banners for unverified phone/email.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.get_organisation

        # Include subscription status in the /me response
        sub_data = None
        if org:
            sub = org.subscriptions.order_by("-created_at").first()
            if sub:
                sub_data = {
                    "status":         sub.status,
                    "is_trial":       sub.is_trial,
                    "is_active_now":  sub.is_active_now,
                    "days_remaining": sub.days_remaining,
                    "end_date":       str(sub.end_date),
                }

        return success_response(
            data={
                "user":         UserSerializer(request.user).data,
                "subscription": sub_data,
                "verification": {
                    "phone_verified": request.user.is_phone_verified,
                    "email_verified": request.user.is_email_verified,
                },
            },
            message="User profile retrieved.",
        )

    def patch(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors, status=400)
        serializer.save()
        logger.info("User %s updated their profile.", request.user.phone)
        return success_response(
            data=UserSerializer(request.user).data,
            message="Profile updated successfully.",
        )


class ChangePasswordView(APIView):
    """
    POST /api/v1/accounts/me/change-password/
    Requires old_password + new_password + new_password_confirm.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        if not request.user.check_password(serializer.validated_data["old_password"]):
            return error_response(
                "Current password is incorrect.",
                errors={"old_password": ["Incorrect password."]},
                status=400,
            )

        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        logger.info("User %s changed their password.", request.user.phone)
        return success_response(message="Password changed successfully.")


# ── User management ───────────────────────────────────────────────────────────

def _annotate_with_stats(queryset):
    today = timezone.now().date()
    try:
        return queryset.annotate(
            _sales_today=Sum(
                "transactions__total",
                filter=Q(transactions__created_at__date=today, transactions__status="paid"),
            ),
            _txns_today=Count(
                "transactions",
                filter=Q(transactions__created_at__date=today),
            ),
            _total_sales=Sum(
                "transactions__total",
                filter=Q(transactions__status="paid"),
            ),
            _avg_ticket=Avg(
                "transactions__total",
                filter=Q(transactions__status="paid"),
            ),
            _txns_total=Count("transactions"),
        )
    except Exception:
        return queryset


class UserViewSet(ModelViewSet):
    """
    CRUD endpoints for user/staff management.

    GET    /api/v1/accounts/users/              → list (owner sees own org; admin sees all)
    POST   /api/v1/accounts/users/              → create staff member
    GET    /api/v1/accounts/users/{id}/         → staff detail
    PATCH  /api/v1/accounts/users/{id}/         → update profile / shift / permissions
    DELETE /api/v1/accounts/users/{id}/         → deactivate (soft delete)

    Query params:
      ?store=<id>              → filter by store
      ?role=owner|staff
      ?employment_status=active|on_leave|inactive
      ?search=<name_or_phone>
    """

    queryset = User.objects.select_related("store", "store__organisation", "organisation").all()
    permission_classes = [IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ("update", "partial_update"):
            return UserUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == User.ROLE_ADMIN:
            return qs   # system admin sees everyone
        # Owners see only users in their organisation
        org = user.get_organisation
        if org:
            qs = qs.filter(
                Q(organisation=org) | Q(store__organisation=org)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        # Automatically assign to owner's organisation
        user = serializer.save()
        if not user.organisation_id and request.user.get_organisation:
            user.organisation = request.user.get_organisation
            user.save(update_fields=["organisation", "updated_at"])

        logger.info("User %s created staff member %s.", request.user.phone, user.phone)
        return created_response(
            data=UserSerializer(user).data,
            message=f"Staff member '{user.full_name}' created.",
        )

    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(data=UserSerializer(user).data, message="Staff member updated.")

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.employment_status = User.EMPLOYMENT_INACTIVE
        user.is_active = False
        user.save(update_fields=["employment_status", "is_active", "updated_at"])
        logger.info("User %s deactivated %s.", request.user.phone, user.phone)
        return success_response(message=f"'{user.full_name}' deactivated.")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        store_id = request.query_params.get("store")
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        role = request.query_params.get("role")
        if role:
            queryset = queryset.filter(role=role)

        employment_status = request.query_params.get("employment_status")
        if employment_status:
            queryset = queryset.filter(employment_status=employment_status)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search)
            )

        queryset = _annotate_with_stats(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = UserSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = UserSerializer(queryset, many=True)
        return success_response(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        annotated = _annotate_with_stats(User.objects.filter(pk=instance.pk)).first()
        serializer = UserSerializer(annotated or instance)
        return success_response(data=serializer.data)

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request, pk=None):
        """GET /api/v1/accounts/users/{id}/stats/"""
        user = self.get_object()
        today = timezone.now().date()
        try:
            txn_qs       = user.transactions.all()
            sales_today  = txn_qs.filter(created_at__date=today, status="paid").aggregate(t=Sum("total"))["t"] or 0
            total_sales  = txn_qs.filter(status="paid").aggregate(t=Sum("total"))["t"] or 0
            avg_ticket   = round(txn_qs.filter(status="paid").aggregate(a=Avg("total"))["a"] or 0)
            txns_today   = txn_qs.filter(created_at__date=today).count()
            txns_total   = txn_qs.count()
        except Exception:
            sales_today = total_sales = avg_ticket = txns_today = txns_total = 0

        return success_response(data=StaffStatsSerializer({
            "user_id": user.pk, "full_name": user.full_name,
            "sales_today": sales_today, "total_sales": total_sales,
            "avg_ticket": avg_ticket, "txns_today": txns_today, "txns_total": txns_total,
        }).data)

    @action(detail=False, methods=["get"], url_path="kpis")
    def kpis(self, request):
        """GET /api/v1/accounts/users/kpis/ — store-level staff KPIs."""
        org = request.user.get_organisation
        if not org:
            return error_response("User has no organisation.", status=400)

        # Scope to the user's store if they are staff, else entire org
        if request.user.role == User.ROLE_STAFF and request.user.store_id:
            qs = User.objects.filter(store=request.user.store)
        else:
            qs = User.objects.filter(
                Q(organisation=org) | Q(store__organisation=org)
            )

        today   = timezone.now().date()
        total   = qs.count()
        active  = qs.filter(employment_status=User.EMPLOYMENT_ACTIVE).count()
        on_leave = qs.filter(employment_status=User.EMPLOYMENT_ON_LEAVE).count()

        weekday = timezone.now().weekday()
        if weekday < 5:
            on_shift = qs.filter(employment_status=User.EMPLOYMENT_ACTIVE).exclude(
                shift=User.SHIFT_WEEKEND
            ).count()
        else:
            on_shift = qs.filter(
                employment_status=User.EMPLOYMENT_ACTIVE,
                shift__in=(User.SHIFT_WEEKEND, User.SHIFT_FULL_DAY),
            ).count()

        try:
            from apps.transactions.models import Transaction
            store_filter = (
                Q(store__organisation=org) if request.user.role != User.ROLE_STAFF
                else Q(store=request.user.store)
            )
            sales_today = Transaction.objects.filter(
                store_filter, created_at__date=today, status="paid"
            ).aggregate(t=Sum("total"))["t"] or 0
            txns_today = Transaction.objects.filter(
                store_filter, created_at__date=today
            ).count()
        except Exception:
            sales_today = txns_today = 0

        return success_response(data={
            "total_staff":    total,
            "active":         active,
            "on_leave":       on_leave,
            "on_shift_today": on_shift,
            "sales_today":    sales_today,
            "txns_today":     txns_today,
        })


# ── Store management ──────────────────────────────────────────────────────────

class StoreViewSet(ModelViewSet):
    """
    GET    /api/v1/accounts/stores/       → list stores
    POST   /api/v1/accounts/stores/       → create a store (owner only, within max_stores limit)
    GET    /api/v1/accounts/stores/{id}/  → store detail
    PATCH  /api/v1/accounts/stores/{id}/  → update store
    """

    queryset = Store.objects.select_related("organisation").prefetch_related("staff")
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == User.ROLE_ADMIN:
            return qs
        org = user.get_organisation
        if org:
            return qs.filter(organisation=org)
        return qs.none()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        return success_response(
            data=self.get_serializer(queryset, many=True).data,
            message=f"{queryset.count()} store(s) retrieved.",
        )

    def create(self, request, *args, **kwargs):
        org = request.user.get_organisation
        if not org:
            return error_response("No organisation found for this account.", status=400)

        # Enforce max_stores limit
        current_count = org.stores.filter(is_active=True).count()
        if current_count >= org.max_stores:
            return error_response(
                f"You have reached your maximum store limit ({org.max_stores}). "
                "Purchase an extra store slot to add more branches.",
                status=403,
            )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        store = serializer.save(organisation=org)
        logger.info("Owner %s created store '%s'.", request.user.phone, store.name)
        return created_response(
            data=StoreSerializer(store).data,
            message=f"Store '{store.name}' created.",
        )


# ── Organisation ──────────────────────────────────────────────────────────────

class OrganisationView(APIView):
    """
    GET   /api/v1/accounts/organisation/  → get current org
    PATCH /api/v1/accounts/organisation/  → update org settings

    Owners can view and update their own organisation.
    System admins can view any (but should use Django admin for full management).
    """

    permission_classes = [IsAuthenticated, IsOwner]

    def _get_org(self, user):
        return user.get_organisation

    def get(self, request):
        org = self._get_org(request.user)
        if not org:
            return error_response("No organisation found for this user.", status=404)
        return success_response(
            data=OrganisationSerializer(org).data,
            message="Organisation retrieved.",
        )

    def patch(self, request):
        org = self._get_org(request.user)
        if not org:
            return error_response("No organisation found.", status=404)
        serializer = OrganisationSerializer(org, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(data=serializer.data, message="Organisation updated.")


# ── AI Credits ────────────────────────────────────────────────────────────────

class AICreditView(APIView):
    """
    GET /api/v1/accounts/ai-credits/
    Returns current month's AI credit usage for the user's organisation.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.get_organisation
        if not org:
            return error_response("No organisation linked to this account.", status=400)

        credit = AICredit.get_or_create_current(org)
        return success_response(
            data=AICreditSerializer(credit).data,
            message="AI credits retrieved.",
        )

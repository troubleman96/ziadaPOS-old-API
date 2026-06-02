"""
apps/accounts/api/views.py

API views for accounts: users, stores, organisations, AI credits.

All views use our standard response envelope (apps.core.response).
Authentication is JWT — provided via 'Authorization: Bearer <token>' header.
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

from apps.core.permissions import IsOrganisationAdmin, IsStoreManager
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
    StaffStatsSerializer,
    StoreSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)


# ── Current User ("me") ───────────────────────────────────────────────────────

class MeView(APIView):
    """
    GET  /api/v1/accounts/me/  → return the currently logged-in user's profile
    PATCH /api/v1/accounts/me/ → update profile fields

    Referenced by:
      - Sidenav footer: displays name, role, avatar initials
      - Dashboard greeting: "Good afternoon, Hamisi"
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the current user's full profile."""
        serializer = UserSerializer(request.user)
        return success_response(
            data=serializer.data,
            message="User profile retrieved.",
        )

    def patch(self, request):
        """Partially update the current user's profile (no password change here)."""
        serializer = UserUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
                status=400,
            )
        serializer.save()
        logger.info("User %s updated their profile.", request.user.username)
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
        """Change the current user's password after verifying old one."""
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        # Verify old password is correct
        if not request.user.check_password(serializer.validated_data["old_password"]):
            return error_response(
                "Current password is incorrect.",
                errors={"old_password": ["Incorrect password."]},
                status=400,
            )

        # Set the new password (hashes it internally)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()

        logger.info("User %s changed their password.", request.user.username)
        return success_response(message="Password changed successfully.")


# ── User management ───────────────────────────────────────────────────────────

def _annotate_with_stats(queryset):
    """
    Annotate a User queryset with today's and all-time transaction stats.
    Requires Transaction.cashier to be the reverse FK (related_name='transactions').
    Wrapped in try/except so it degrades gracefully if the transactions app is unavailable.
    """
    today = timezone.now().date()
    try:
        return queryset.annotate(
            _sales_today=Sum(
                "transactions__total",
                filter=Q(
                    transactions__created_at__date=today,
                    transactions__status="paid",
                ),
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
    CRUD endpoints for staff / user management.

    GET    /api/v1/accounts/users/              → list all users (manager+ sees own store)
    POST   /api/v1/accounts/users/              → create a new staff member
    GET    /api/v1/accounts/users/{id}/         → staff detail with performance stats
    PATCH  /api/v1/accounts/users/{id}/         → update profile / shift / permissions
    DELETE /api/v1/accounts/users/{id}/         → deactivate (soft delete)
    GET    /api/v1/accounts/users/{id}/stats/   → isolated performance stats for one user
    GET    /api/v1/accounts/users/kpis/         → store-level staff KPIs (count, on-shift, etc.)

    Query params for list:
      ?store=<id>              → filter by store
      ?role=admin|manager|cashier
      ?employment_status=active|on_leave|inactive
      ?search=<name_or_phone>
    """

    queryset = User.objects.select_related("store", "store__organisation").all()
    permission_classes = [IsAuthenticated, IsStoreManager]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ("update", "partial_update"):
            return UserUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        # Non-admins are scoped to their own store
        if self.request.user.role not in (User.ROLE_ADMIN,):
            if self.request.user.store_id:
                qs = qs.filter(store=self.request.user.store)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        user = serializer.save()
        logger.info("User %s created staff member %s.", request.user.username, user.username)
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
        return success_response(
            data=UserSerializer(user).data,
            message="Staff member updated.",
        )

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.employment_status = User.EMPLOYMENT_INACTIVE
        user.is_active = False
        user.save(update_fields=["employment_status", "is_active", "updated_at"])
        logger.info("User %s deactivated %s.", request.user.username, user.username)
        return success_response(message=f"'{user.full_name}' deactivated.")

    def list(self, request, *args, **kwargs):
        """
        List staff members with optional filters and performance stats.
        """
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
        """Return a single staff member with fully-computed performance stats."""
        instance = self.get_object()
        # Annotate the single object so stats are computed via DB aggregation
        annotated = _annotate_with_stats(
            User.objects.filter(pk=instance.pk)
        ).first()
        serializer = UserSerializer(annotated or instance)
        return success_response(data=serializer.data)

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request, pk=None):
        """
        GET /api/v1/accounts/users/{id}/stats/
        Returns isolated performance stats for one staff member.
        """
        user = self.get_object()
        today = timezone.now().date()

        try:
            txn_qs = user.transactions.all()
            sales_today = txn_qs.filter(
                created_at__date=today, status="paid"
            ).aggregate(t=Sum("total"))["t"] or 0
            total_sales = txn_qs.filter(status="paid").aggregate(
                t=Sum("total")
            )["t"] or 0
            avg_result = txn_qs.filter(status="paid").aggregate(a=Avg("total"))["a"]
            avg_ticket = round(avg_result or 0)
            txns_today = txn_qs.filter(created_at__date=today).count()
            txns_total = txn_qs.count()
        except Exception:
            sales_today = total_sales = avg_ticket = txns_today = txns_total = 0

        data = {
            "user_id":     user.pk,
            "full_name":   user.full_name,
            "sales_today": sales_today,
            "total_sales": total_sales,
            "avg_ticket":  avg_ticket,
            "txns_today":  txns_today,
            "txns_total":  txns_total,
        }
        return success_response(data=StaffStatsSerializer(data).data)

    @action(detail=False, methods=["get"], url_path="kpis")
    def kpis(self, request):
        """
        GET /api/v1/accounts/users/kpis/
        Store-level staff KPIs: total count, active, on shift today, sales today.
        """
        store = request.user.store
        if not store:
            return error_response("User is not assigned to a store.", status=400)

        qs = User.objects.filter(store=store)
        today = timezone.now().date()

        total       = qs.count()
        active      = qs.filter(employment_status=User.EMPLOYMENT_ACTIVE).count()
        on_leave    = qs.filter(employment_status=User.EMPLOYMENT_ON_LEAVE).count()
        # "On shift today" = active and shift is not Weekend (on weekdays)
        # This is a simplification; a real scheduler would check the actual day
        weekday = timezone.now().weekday()  # 0=Mon, 5=Sat, 6=Sun
        if weekday < 5:  # Weekday
            on_shift = qs.filter(
                employment_status=User.EMPLOYMENT_ACTIVE,
            ).exclude(shift=User.SHIFT_WEEKEND).count()
        else:  # Weekend
            on_shift = qs.filter(
                employment_status=User.EMPLOYMENT_ACTIVE,
                shift=User.SHIFT_WEEKEND,
            ).count() + qs.filter(
                employment_status=User.EMPLOYMENT_ACTIVE,
                shift=User.SHIFT_FULL_DAY,
            ).count()

        try:
            from apps.transactions.models import Transaction
            sales_today = Transaction.objects.filter(
                cashier__store=store,
                created_at__date=today,
                status="paid",
            ).aggregate(t=Sum("total"))["t"] or 0
            txns_today = Transaction.objects.filter(
                cashier__store=store,
                created_at__date=today,
            ).count()
        except Exception:
            sales_today = txns_today = 0

        return success_response(data={
            "total_staff":   total,
            "active":        active,
            "on_leave":      on_leave,
            "on_shift_today": on_shift,
            "sales_today":   sales_today,
            "txns_today":    txns_today,
        })


# ── Store management ──────────────────────────────────────────────────────────

class StoreViewSet(ModelViewSet):
    """
    CRUD endpoints for store management.

    GET    /api/v1/accounts/stores/       → list stores
    POST   /api/v1/accounts/stores/       → create a store
    GET    /api/v1/accounts/stores/{id}/  → store detail
    PATCH  /api/v1/accounts/stores/{id}/  → update store
    """

    queryset = Store.objects.select_related("organisation").prefetch_related("staff")
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsStoreManager]

    def list(self, request, *args, **kwargs):
        """Return stores. Admin sees all; managers see their own store."""
        queryset = self.get_queryset()

        # Non-admins only see their own store
        if request.user.role != "admin":
            queryset = queryset.filter(id=request.user.store_id)

        serializer = self.get_serializer(queryset, many=True)
        return success_response(
            data=serializer.data,
            message=f"{queryset.count()} store(s) retrieved.",
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        store = serializer.save()
        logger.info("Admin %s created store '%s'.", request.user.username, store.name)
        return created_response(
            data=StoreSerializer(store).data,
            message=f"Store '{store.name}' created.",
        )


# ── Organisation ──────────────────────────────────────────────────────────────

class OrganisationView(APIView):
    """
    GET   /api/v1/accounts/organisation/  → get current org
    PATCH /api/v1/accounts/organisation/  → update org settings

    Only admins can see/update organisation settings.
    """

    permission_classes = [IsAuthenticated, IsOrganisationAdmin]

    def _get_org(self, user):
        """Get the organisation for the current user via their store."""
        if user.store and user.store.organisation:
            return user.store.organisation
        return None

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

    Referenced by:
      - Sidenav footer: "AI CREDITS · MAY  2,418 / 5,000"
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current month AI credits for the user's organisation."""
        if not request.user.store:
            return error_response("User is not assigned to a store.", status=400)

        org = request.user.store.organisation
        credit = AICredit.get_or_create_current(org)
        return success_response(
            data=AICreditSerializer(credit).data,
            message="AI credits retrieved.",
        )

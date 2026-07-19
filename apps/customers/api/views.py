"""
apps/customers/api/views.py

API views for the Customers app.

Referenced UI pages:
  /customers        → CustomerViewSet.list()   (segmented table, sortable, searchable)
  /customers/[id]   → CustomerViewSet.retrieve() (full profile with history)
  /customers/new    → CustomerViewSet.create()  (add customer form)
  /pos              → Used by CompleteSaleSerializer.customer_id field

Endpoints:
  GET    /api/v1/customers/         → list (filtered, paginated)
  POST   /api/v1/customers/         → create new customer
  GET    /api/v1/customers/{id}/    → retrieve full detail
  PATCH  /api/v1/customers/{id}/    → update contact info / segment
  DELETE /api/v1/customers/{id}/    → soft-delete (is_active=False)
  GET    /api/v1/customers/summary/ → KPI aggregate stats
  POST   /api/v1/customers/{id}/send-sms/ → send an ad-hoc SMS via SendAfrica
"""

import logging

from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.core.permissions import IsStoreManager
from apps.core.response import created_response, error_response, no_content_response, success_response

from ..models import Customer
from .serializers import (
    CustomerCreateSerializer,
    CustomerListSerializer,
    CustomerSerializer,
    CustomerUpdateSerializer,
    SendCustomerSmsSerializer,
)

logger = logging.getLogger(__name__)


class CustomerViewSet(ModelViewSet):
    """
    ViewSet for the Customer directory.

    Provides the full CRUD surface needed by the /customers page:
      - List with segment filter, search, and sort
      - Detail with full profile
      - Create from "Add customer" form or the /pos customer selector
      - Update for contact edits and segment changes
      - Soft-delete to preserve transaction history

    All operations are scoped to the requesting user's store.
    Managers and admins can create/update/delete; cashiers are read-only.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "phone", "email"]
    ordering_fields = ["total_spent", "last_visit", "avg_ticket", "open_credit", "created_at"]
    ordering = ["-total_spent"]  # Default: VIPs first

    def get_queryset(self):
        """
        Return customers scoped to the user's store, with optional filters.

        Query params supported:
          ?segment=VIP|Regular|Occasional|New   → filter by segment
          ?has_credit=true                       → only customers with open credit
          ?is_active=true|false                  → include/exclude inactive
          ?search=Fatuma                         → search name/phone/email
          ?ordering=-total_spent                 → sort
        """
        qs = Customer.objects.filter(
            store=self.request.user.store,
            is_active=True,
        )

        # Segment filter (?segment=VIP)
        segment = self.request.query_params.get("segment")
        if segment and segment != "All":
            qs = qs.filter(segment=segment)

        # Credit filter (?has_credit=true) — used by /credits page
        has_credit = self.request.query_params.get("has_credit")
        if has_credit and has_credit.lower() == "true":
            qs = qs.filter(open_credit__gt=0)

        # Include inactive if explicitly requested by managers
        is_active = self.request.query_params.get("is_active")
        if is_active and is_active.lower() == "false":
            qs = Customer.objects.filter(
                store=self.request.user.store,
                is_active=False,
            )

        return qs

    def get_serializer_class(self):
        """
        Use lightweight serialiser for list, full for detail, write-specific for mutations.
        """
        if self.action == "create":
            return CustomerCreateSerializer
        if self.action in ("update", "partial_update"):
            return CustomerUpdateSerializer
        if self.action == "list":
            return CustomerListSerializer
        return CustomerSerializer

    # ── List ─────────────────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        """
        GET /api/v1/customers/
        Returns paginated customer list for the /customers page.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/customers/
        Create a new customer. Only managers and admins may create.
        """
        # Only managers/admins can create customers
        if not IsStoreManager().has_permission(request, self):
            return error_response("Only store managers can add customers.", status=403)

        # Pass store into serializer context so unique validation works
        serializer = CustomerCreateSerializer(
            data=request.data,
            context={"request": request, "store": request.user.store},
        )
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        # Inject store from the authenticated user
        customer = serializer.save(store=request.user.store)

        logger.info(
            "User %s created customer %s (%s)",
            request.user.username, customer.name, customer.id,
        )
        return created_response(
            data=CustomerSerializer(customer).data,
            message=f"Customer '{customer.name}' added.",
        )

    # ── Retrieve ─────────────────────────────────────────────────────────────

    def retrieve(self, request, *args, **kwargs):
        """
        GET /api/v1/customers/{id}/
        Full customer profile with stats.
        """
        customer = self.get_object()
        return success_response(
            data=CustomerSerializer(customer).data,
            message="Customer profile.",
        )

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, request, *args, **kwargs):
        """
        PATCH /api/v1/customers/{id}/
        Partial update: name, phone, email, segment, notes.
        Only managers/admins may update.
        """
        if not IsStoreManager().has_permission(request, self):
            return error_response("Only store managers can edit customer records.", status=403)

        partial = kwargs.pop("partial", False)
        customer = self.get_object()
        serializer = CustomerUpdateSerializer(customer, data=request.data, partial=partial)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        customer = serializer.save()
        return success_response(
            data=CustomerSerializer(customer).data,
            message="Customer updated.",
        )

    def partial_update(self, request, *args, **kwargs):
        """Delegate PATCH to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # ── Soft-delete ───────────────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/v1/customers/{id}/
        Soft-delete: marks is_active=False.
        Transactions and credit tabs referencing this customer are NOT affected.
        Only managers/admins may delete.
        """
        if not IsStoreManager().has_permission(request, self):
            return error_response("Only store managers can remove customers.", status=403)

        customer = self.get_object()
        customer.is_active = False
        customer.save(update_fields=["is_active", "updated_at"])

        logger.info(
            "User %s soft-deleted customer %s (%s)",
            request.user.username, customer.name, customer.id,
        )
        return no_content_response()

    # ── Summary KPI action ────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """
        GET /api/v1/customers/summary/

        Returns aggregate stats for the /customers KPI strip:
          - total_customers (all active)
          - by_segment (count per segment)
          - total_lifetime_value (sum of total_spent)
          - active_this_month (last_visit within 30 days)
          - on_credit_count (customers with open_credit > 0)
          - total_open_credit (sum of open_credit)
          - avg_ticket (store-wide average)
        """
        from django.db.models import Avg, Count, Sum
        from django.utils import timezone

        qs = self.filter_queryset(self.get_queryset())

        agg = qs.aggregate(
            total_customers=Count("id"),
            total_lifetime_value=Sum("total_spent"),
            total_open_credit=Sum("open_credit"),
            avg_ticket=Avg("avg_ticket"),
        )

        # Segment breakdown
        by_segment = dict(
            qs.values("segment").annotate(count=Count("id")).values_list("segment", "count")
        )

        # Active this month = visited in last 30 days
        from datetime import timedelta
        cutoff = timezone.now().date() - timedelta(days=30)
        active_this_month = qs.filter(last_visit__gte=cutoff).count()

        on_credit_count = qs.filter(open_credit__gt=0).count()

        data = {
            "total_customers":       agg["total_customers"] or 0,
            "total_lifetime_value":  agg["total_lifetime_value"] or 0,
            "total_open_credit":     agg["total_open_credit"] or 0,
            "avg_ticket":            int(agg["avg_ticket"] or 0),
            "active_this_month":     active_this_month,
            "on_credit_count":       on_credit_count,
            "by_segment":            by_segment,
        }
        return success_response(data=data, message="Customer summary.")

    # ── Send SMS ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="send-sms")
    def send_sms(self, request, pk=None):
        """
        POST /api/v1/customers/{id}/send-sms/

        Sends an ad-hoc SMS to this customer via SendAfrica (not tied to
        credit reminders — for the customer detail page's "Message" action).
        Requires the organisation to have a SendAfrica API key configured
        in Settings → Integrations.
        """
        from apps.notifications.sms import SmsError, send_sms as send_sms_via_provider

        customer = self.get_object()

        serializer = SendCustomerSmsSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        try:
            result = send_sms_via_provider(
                request.user.get_organisation,
                customer.phone,
                serializer.validated_data["message"],
            )
        except SmsError as exc:
            return error_response(str(exc), status=400, errors={"code": exc.code})

        logger.info(
            "User %s sent SMS to customer %s (%s), message_id=%s",
            request.user.username, customer.name, customer.id, result.get("message_id"),
        )
        return success_response(data=result, message="SMS sent.")

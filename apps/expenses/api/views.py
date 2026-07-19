import logging

from django.db.models import Count, Q, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.permissions import IsStoreStaff
from apps.core.pagination import StandardResultsPagination
from apps.core.response import (
    created_response,
    error_response,
    no_content_response,
    success_response,
)

from ..models import Expense
from .serializers import (
    CreateExpenseSerializer,
    ExpenseDetailSerializer,
    ExpenseListSerializer,
    UpdateExpenseInputSerializer,
)

logger = logging.getLogger(__name__)


def get_expense_or_404(expense_id, store):
    try:
        expense = Expense.objects.select_related("recorded_by").get(
            id=expense_id, store=store)
        return expense, None
    except Expense.DoesNotExist:
        return None, error_response(
            f"Expense {expense_id} not found.", status=404)


class ExpenseListView(APIView):
    permission_classes = [IsAuthenticated, IsStoreStaff]

    def get(self, request):
        store = request.user.store
        qs = Expense.objects.select_related("recorded_by").filter(store=store)

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(notes__icontains=search)
                | Q(payment_reference__icontains=search)
            )

        cat = request.query_params.get("category")
        if cat:
            qs = qs.filter(category=cat)

        method = request.query_params.get("payment_method")
        if method:
            qs = qs.filter(payment_method=method)

        ordering = request.query_params.get("ordering", "-created_at")
        allowed = ["amount", "-amount", "created_at", "-created_at",
                   "category", "-category"]
        base = ordering[1:] if ordering.startswith("-") else ordering
        if base not in [a.lstrip("-") for a in allowed]:
            ordering = "-created_at"
        qs = qs.order_by(ordering)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = ExpenseListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = ExpenseListSerializer(qs, many=True)
        return success_response(data=serializer.data, message="Expenses retrieved.")

    def post(self, request):
        ser = CreateExpenseSerializer(data=request.data)
        if not ser.is_valid():
            return error_response("Validation failed.", errors=ser.errors)

        d = ser.validated_data
        expense = Expense.objects.create(
            store=request.user.store,
            title=d["title"],
            category=d["category"],
            amount=d["amount"],
            payment_method=d["payment_method"],
            payment_reference=d.get("payment_reference", ""),
            notes=d.get("notes", ""),
            receipt_url=d.get("receipt_url", ""),
            recorded_by=request.user,
        )
        logger.info("User %s recorded expense %s (%s)", request.user.username, expense.id, expense.title)
        return created_response(
            data=ExpenseDetailSerializer(expense).data,
            message="Expense recorded.",
        )


class ExpenseDetailView(APIView):
    permission_classes = [IsAuthenticated, IsStoreStaff]

    def get(self, request, pk):
        expense, err = get_expense_or_404(pk, request.user.store)
        if err:
            return err
        return success_response(data=ExpenseDetailSerializer(expense).data)

    def patch(self, request, pk):
        expense, err = get_expense_or_404(pk, request.user.store)
        if err:
            return err

        ser = UpdateExpenseInputSerializer(data=request.data)
        if not ser.is_valid():
            return error_response("Validation failed.", errors=ser.errors)

        d = ser.validated_data
        update_fields = []
        for field in ["title", "category", "payment_method",
                       "payment_reference", "notes"]:
            if field in d:
                setattr(expense, field, d[field])
                update_fields.append(field)
        if "amount" in d:
            expense.amount = d["amount"]
            update_fields.append("amount")

        if update_fields:
            update_fields.append("updated_at")
            expense.save(update_fields=update_fields)

        expense.refresh_from_db()
        return success_response(data=ExpenseDetailSerializer(expense).data)

    def delete(self, request, pk):
        expense, err = get_expense_or_404(pk, request.user.store)
        if err:
            return err
        eid = str(expense.id)
        expense.delete()
        logger.info("User %s deleted expense %s", request.user.username, eid)
        return no_content_response()


class ExpenseSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsStoreStaff]

    def get(self, request):
        qs = Expense.objects.filter(store=request.user.store)
        total_amount = qs.aggregate(s=Sum("amount"))["s"] or 0
        total_count = qs.count()

        by_category = (
            qs.values("category")
            .annotate(amount=Sum("amount"), count=Count("id"))
            .order_by("-amount")
        )
        denom_cat = total_amount or 1
        by_category_list = [
            {
                "category": c["category"],
                "amount": c["amount"],
                "count": c["count"],
                "pct": round(c["amount"] / denom_cat * 100, 1),
            }
            for c in by_category
        ]

        by_method = (
            qs.values("payment_method")
            .annotate(amount=Sum("amount"), count=Count("id"))
            .order_by("-amount")
        )
        denom_met = total_amount or 1
        by_method_list = [
            {
                "method": m["payment_method"],
                "amount": m["amount"],
                "count": m["count"],
                "pct": round(m["amount"] / denom_met * 100, 1),
            }
            for m in by_method
        ]

        recent = qs.select_related("recorded_by").order_by("-created_at")[:5]
        recent_ser = ExpenseListSerializer(recent, many=True)

        return success_response(data={
            "total_amount": total_amount,
            "total_count": total_count,
            "by_category": by_category_list,
            "by_method": by_method_list,
            "recent": recent_ser.data,
        })

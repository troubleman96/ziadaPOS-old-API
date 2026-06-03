"""
apps/reports/api/views.py

API views for the reports app.

Referenced UI page: /reports (three tabs: Overview, Scheduled, History)

Endpoints:
  GET  /api/v1/reports/types/                 → list available report types
  POST /api/v1/reports/generate/              → generate a report (CSV download or JSON data)
  GET  /api/v1/reports/exports/               → export history list
  GET  /api/v1/reports/exports/{id}/download/ → re-download a previously generated export
  GET  /api/v1/reports/scheduled/             → list all scheduled reports
  POST /api/v1/reports/scheduled/             → create a new scheduled report
  PATCH /api/v1/reports/scheduled/{id}/       → update or toggle a scheduled report
  DELETE /api/v1/reports/scheduled/{id}/      → delete a scheduled report

Generate flow:
  1. Deserialise and validate the request body (report_type, format, date range)
  2. Call get_report_data() → structured dict
  3. If format=csv: return an HTTP response with Content-Disposition attachment header
     and text/csv content type (triggers browser file download)
  4. If format=json: return standard API envelope with the report data
  5. Create a ReportExport audit record in both cases
"""

import logging

from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.permissions import IsStoreManager
from apps.core.response import success_response

from ..models import (
    FORMAT_CSV, FORMAT_JSON,
    REPORT_TYPE_CHOICES,
    ReportExport,
    ScheduledReport,
)
from ..services import (
    build_csv,
    compute_next_send,
    get_report_data,
    parse_range_for_report,
)
from .serializers import (
    GenerateReportSerializer,
    ReportExportSerializer,
    ScheduledReportListSerializer,
    ScheduledReportSerializer,
)

logger = logging.getLogger(__name__)


# ── Report Types ──────────────────────────────────────────────────────────────

class ReportTypesView(APIView):
    """
    GET /api/v1/reports/types/

    Returns a static list of available report types with metadata.
    Used by the /reports Overview tab to render the QuickExportCard grid.

    No date range needed — this is just the catalogue of what can be generated.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        types = [
            {
                "id":       "sales",
                "name":     "Sales Summary",
                "desc":     "Daily sales totals, top products, payment breakdown and revenue by category.",
                "color":    "accent",
                "supports_date_range": True,
            },
            {
                "id":       "inventory",
                "name":     "Inventory Valuation",
                "desc":     "Cost and retail value of all stock on hand, sorted by category.",
                "color":    "good",
                "supports_date_range": False,  # Always as-of-today
            },
            {
                "id":       "tax",
                "name":     "Tax Statement",
                "desc":     "VAT collected, taxable revenue and TRA-ready summary for compliance.",
                "color":    "warn",
                "supports_date_range": True,
            },
            {
                "id":       "credit",
                "name":     "Credit Aged Debtors",
                "desc":     "Accounts receivable aged 0–30, 31–60, 61–90, 90+ days with contact details.",
                "color":    "bad",
                "supports_date_range": False,  # Always current as-of-today
            },
        ]
        return success_response(data={"report_types": types}, message="Available report types.")


# ── Generate Report ───────────────────────────────────────────────────────────

class GenerateReportView(APIView):
    """
    POST /api/v1/reports/generate/

    Generates a report and returns it as a CSV file download or JSON data.

    Request body:
      {
        "report_type": "sales" | "inventory" | "tax" | "credit",
        "format": "csv" | "json",
        "range": "7d" | "30d" | "90d" | "month" | "ytd",   // OR:
        "date_from": "2026-05-01",
        "date_to": "2026-05-24"
      }

    CSV response:
      Content-Type: text/csv; charset=utf-8
      Content-Disposition: attachment; filename="sales-summary-2026-05.csv"
      <csv body>

    JSON response:
      Standard API envelope with "data": { ...report data... }

    Side effect:
      Creates a ReportExport audit record in both cases.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store       = request.user.store
        report_type = serializer.validated_data["report_type"]
        fmt         = serializer.validated_data.get("format", FORMAT_CSV)

        # Parse date range from the validated input
        start, end, period_label = parse_range_for_report(serializer.validated_data)

        # Generate the report data
        try:
            data = get_report_data(report_type, store, start, end)
        except Exception as exc:
            logger.exception("Report generation failed: %s", exc)
            return success_response(
                data=None,
                message="Report generation failed. Please try again.",
                status=500,
            )

        # Build the filename-safe report name for history display
        report_name = dict(REPORT_TYPE_CHOICES).get(report_type, report_type.title())

        if fmt == FORMAT_CSV:
            csv_str, fname = build_csv(report_type, data)
            file_size      = len(csv_str.encode("utf-8"))

            # Create audit record before returning (so it's recorded even on re-open)
            ReportExport.objects.create(
                store=store,
                organisation=store.organisation,
                created_by=request.user,
                report_type=report_type,
                name=report_name,
                period_label=period_label,
                date_from=start,
                date_to=end,
                format=FORMAT_CSV,
                file_size_bytes=file_size,
            )

            response = HttpResponse(csv_str, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{fname}"'
            return response

        else:
            # JSON / PDF-data response
            import json
            json_str  = json.dumps(data, default=str)
            file_size = len(json_str.encode("utf-8"))

            ReportExport.objects.create(
                store=store,
                organisation=store.organisation,
                created_by=request.user,
                report_type=report_type,
                name=report_name,
                period_label=period_label,
                date_from=start,
                date_to=end,
                format=FORMAT_JSON,
                file_size_bytes=file_size,
            )

            return success_response(
                data={
                    "report_type":   report_type,
                    "period_label":  period_label,
                    "date_from":     start.isoformat(),
                    "date_to":       end.isoformat(),
                    "report":        data,
                },
                message=f"{report_name} report data.",
                status=200,
            )


# ── Export History ────────────────────────────────────────────────────────────

class ExportListView(APIView):
    """
    GET /api/v1/reports/exports/

    Returns the export history for this store.
    Used by the /reports → History tab.

    Query params:
      ?report_type=sales|inventory|tax|credit  (optional filter)
      ?format=csv|json                         (optional filter)
      ?limit=50                                (default 50, max 200)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = request.user.store
        qs = ReportExport.objects.filter(store=store).order_by("-created_at")

        # Optional filters
        if rt := request.query_params.get("report_type"):
            qs = qs.filter(report_type=rt)
        if fmt := request.query_params.get("format"):
            qs = qs.filter(format=fmt)

        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
        except ValueError:
            limit = 50

        exports = ReportExportSerializer(qs[:limit], many=True).data

        return success_response(
            data={"exports": exports, "total": qs.count()},
            message="Export history.",
        )


class ExportDownloadView(APIView):
    """
    GET /api/v1/reports/exports/{export_id}/download/

    Re-generates and streams the export identified by export_id.

    The report data is regenerated on-demand from the stored date_from / date_to
    parameters — it is NOT stored in the database. This means:
      - Downloads always reflect any data corrections made since original export
      - No large BLOBs in the database

    Returns CSV for csv-format exports, JSON data for json-format exports.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, export_id):
        store = request.user.store

        try:
            export = ReportExport.objects.get(id=export_id, store=store)
        except ReportExport.DoesNotExist:
            raise NotFound("Export not found.")

        # Re-generate the report data
        try:
            data = get_report_data(export.report_type, store, export.date_from, export.date_to)
        except Exception as exc:
            logger.exception("Re-download failed: %s", exc)
            return success_response(
                data=None,
                message="Report re-generation failed.",
                status=500,
            )

        if export.format == FORMAT_CSV:
            csv_str, fname = build_csv(export.report_type, data)
            response = HttpResponse(csv_str, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{fname}"'
            return response
        else:
            return success_response(
                data={"report": data, "period_label": export.period_label},
                message="Report data.",
            )


# ── Scheduled Reports ─────────────────────────────────────────────────────────

class ScheduledReportListCreateView(APIView):
    """
    GET  /api/v1/reports/scheduled/ → list all scheduled reports for this store
    POST /api/v1/reports/scheduled/ → create a new scheduled report

    Only store managers and admins can create or modify scheduled reports.
    Cashiers can list but not create.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        store    = request.user.store
        qs       = ScheduledReport.objects.filter(store=store)
        reports  = ScheduledReportListSerializer(qs, many=True).data

        active_count = qs.filter(is_enabled=True).count()

        return success_response(
            data={
                "scheduled_reports": reports,
                "total":             qs.count(),
                "active_count":      active_count,
            },
            message="Scheduled reports.",
        )

    def post(self, request):
        # Only managers/owners can schedule reports
        if not (request.user.role in ("owner", "admin")):
            raise PermissionDenied("Only store owners or admins can schedule reports.")

        store = request.user.store
        serializer = ScheduledReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from django.utils import timezone as tz

        scheduled = serializer.save(
            store=store,
            organisation=store.organisation,
            created_by=request.user,
            next_send_at=compute_next_send(
                serializer.validated_data["frequency"],
                tz.now(),
            ),
        )

        return success_response(
            data=ScheduledReportSerializer(scheduled).data,
            message="Scheduled report created.",
            status=201,
        )


class ScheduledReportDetailView(APIView):
    """
    PATCH  /api/v1/reports/scheduled/{id}/ → update or toggle is_enabled
    DELETE /api/v1/reports/scheduled/{id}/ → delete the scheduled report

    Only managers/owners can modify or delete.

    The PATCH endpoint is used for two UI actions:
      1. Toggle switch: { "is_enabled": true/false }
      2. Edit dialog:   { "name": ..., "frequency": ..., "recipients": [...] }
    """

    permission_classes = [IsAuthenticated]

    def _get_object(self, request, pk):
        """Fetch the ScheduledReport, scoped to this store."""
        try:
            return ScheduledReport.objects.get(id=pk, store=request.user.store)
        except ScheduledReport.DoesNotExist:
            raise NotFound("Scheduled report not found.")

    def _require_manager(self, user):
        if user.role not in ("owner", "admin"):
            raise PermissionDenied("Only store owners or admins can modify scheduled reports.")

    def patch(self, request, pk):
        self._require_manager(request.user)
        scheduled  = self._get_object(request, pk)
        serializer = ScheduledReportSerializer(
            scheduled, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message="Scheduled report updated.",
        )

    def delete(self, request, pk):
        self._require_manager(request.user)
        scheduled = self._get_object(request, pk)
        scheduled.delete()
        return success_response(data=None, message="Scheduled report deleted.")

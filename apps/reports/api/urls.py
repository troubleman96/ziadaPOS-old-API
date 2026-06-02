"""
apps/reports/api/urls.py

Reports routes. Mounted at: /api/v1/reports/

  GET  /types/                        → list available report types + metadata
  POST /generate/                     → generate a report (CSV download or JSON data)
  GET  /exports/                      → export history list (History tab)
  GET  /exports/{export_id}/download/ → re-download a generated export
  GET  /scheduled/                    → list recurring report configurations (Scheduled tab)
  POST /scheduled/                    → create a new scheduled report
  PATCH  /scheduled/{id}/             → update or toggle a scheduled report
  DELETE /scheduled/{id}/             → delete a scheduled report

Authentication: all endpoints require a valid JWT Bearer token.
Management: schedule create/update/delete requires role manager | owner | admin.
"""

from django.urls import path

from .views import (
    ExportDownloadView,
    ExportListView,
    GenerateReportView,
    ReportTypesView,
    ScheduledReportDetailView,
    ScheduledReportListCreateView,
)

urlpatterns = [
    # Catalogue
    path("types/",     ReportTypesView.as_view(),    name="reports-types"),

    # On-demand generation + audit history
    path("generate/",  GenerateReportView.as_view(),  name="reports-generate"),
    path("exports/",   ExportListView.as_view(),       name="reports-exports"),
    path("exports/<uuid:export_id>/download/",
         ExportDownloadView.as_view(),                 name="reports-export-download"),

    # Scheduled reports management
    path("scheduled/",
         ScheduledReportListCreateView.as_view(),      name="reports-scheduled"),
    path("scheduled/<uuid:pk>/",
         ScheduledReportDetailView.as_view(),          name="reports-scheduled-detail"),
]

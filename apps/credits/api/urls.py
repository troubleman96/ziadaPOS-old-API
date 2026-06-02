"""
apps/credits/api/urls.py

Credits routes. Mounted at: /api/v1/credits/

  GET  /                                   → dashboard: KPIs, aging, customer list
  GET  /customers/{id}/                    → full customer credit profile
  POST /customers/{id}/record-payment/     → record a payment from customer
  POST /customers/{id}/send-reminder/      → log a WhatsApp/call/SMS message
  POST /customers/{id}/add-note/           → add internal staff note
  POST /tabs/{id}/write-off/               → write off a credit tab
"""

from django.urls import path

from .views import (
    AddCreditNoteView,
    CreditsDashboardView,
    CustomerCreditProfileView,
    RecordPaymentView,
    SendReminderView,
    WriteOffTabView,
)

urlpatterns = [
    # Dashboard (KPI strip + aging + customer list)
    path("", CreditsDashboardView.as_view(), name="credits-dashboard"),

    # Customer credit profile
    path("customers/<uuid:customer_id>/",
         CustomerCreditProfileView.as_view(), name="credits-customer-profile"),

    # Payment recording
    path("customers/<uuid:customer_id>/record-payment/",
         RecordPaymentView.as_view(), name="credits-record-payment"),

    # Communication log
    path("customers/<uuid:customer_id>/send-reminder/",
         SendReminderView.as_view(), name="credits-send-reminder"),

    # Internal notes
    path("customers/<uuid:customer_id>/add-note/",
         AddCreditNoteView.as_view(), name="credits-add-note"),

    # Write off tab
    path("tabs/<uuid:tab_id>/write-off/",
         WriteOffTabView.as_view(), name="credits-write-off"),
]

"""
apps/credits/api/urls.py

Credits routes. Mounted at: /api/v1/credits/

  GET  /                                   → dashboard: KPIs, aging, customer list
  GET  /customers/{id}/                    → full customer credit profile
  POST /customers/{id}/record-payment/     → record a payment from customer
  POST /customers/{id}/send-reminder/      → log a WhatsApp/call/SMS message
  POST /customers/{id}/add-note/           → add internal staff note
  POST /customers/{id}/issue-credit/       → manually issue credit (no linked sale)
  POST /tabs/{id}/write-off/               → write off a credit tab
  POST /send-all-reminders/                → bulk SendAfrica SMS to all customers with open credit
  POST /draft-reminder/                    → AI-drafted reminder message template
"""

from django.urls import path

from .views import (
    AddCreditNoteView,
    BulkSendRemindersView,
    CreditsDashboardView,
    CustomerCreditProfileView,
    DraftReminderView,
    IssueCreditView,
    RecordPaymentView,
    SendReminderView,
    WriteOffTabView,
)

urlpatterns = [
    # Dashboard (KPI strip + aging + customer list)
    path("", CreditsDashboardView.as_view(), name="credits-dashboard"),

    # Bulk actions (must be before <uuid:customer_id> would-be prefix collisions — none here, but kept together)
    path("send-all-reminders/", BulkSendRemindersView.as_view(), name="credits-send-all-reminders"),
    path("draft-reminder/",     DraftReminderView.as_view(),     name="credits-draft-reminder"),

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

    # Manual credit issuance
    path("customers/<uuid:customer_id>/issue-credit/",
         IssueCreditView.as_view(), name="credits-issue-credit"),

    # Write off tab
    path("tabs/<uuid:tab_id>/write-off/",
         WriteOffTabView.as_view(), name="credits-write-off"),
]

"""
apps/notifications/emails.py

Central email dispatch module.

Functions:
  send_welcome_email(user)              — fired on registration
  send_confirmation_email(user)         — resend-able email verify link
  send_daily_sales_report(store)        — called by scheduler at 22:00 EAT
  send_test_email(to_address)           — sanity check for SMTP configuration
"""

import logging
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

FROM = settings.DEFAULT_FROM_EMAIL
SITE = getattr(settings, "SITE_URL", "https://app.ziadapos.com")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_tzs(v: int) -> str:
    """Format an integer TZS amount like 'TZS 1,240,000'."""
    return f"TZS {v:,}"


def _send(subject: str, to: str, html: str, text: str = "") -> bool:
    """Send an HTML email; return True on success."""
    if not to:
        logger.warning("Email suppressed — no recipient address.")
        return False
    try:
        msg = EmailMultiAlternatives(subject=subject, body=text or subject, from_email=FROM, to=[to])
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
        logger.info("Email '%s' sent to %s.", subject, to)
        return True
    except Exception as exc:
        logger.error("Failed to send email '%s' to %s: %s", subject, to, exc)
        return False


# ── Welcome email ─────────────────────────────────────────────────────────────

def send_welcome_email(user) -> bool:
    """
    Send a branded welcome + email-confirmation email immediately after registration.
    Creates (or refreshes) an EmailVerificationToken for this user.
    """
    from .models import EmailVerificationToken

    # Create / refresh the token
    token_obj, _ = EmailVerificationToken.objects.get_or_create(user=user)
    token_obj.token = __import__("uuid").uuid4()
    token_obj.created_at = timezone.now()
    token_obj.save(update_fields=["token", "created_at"])

    confirm_url = f"{SITE}/api/v1/auth/confirm-email/?token={token_obj.token}"

    org_name = ""
    if hasattr(user, "organisation") and user.organisation:
        org_name = user.organisation.name

    ctx = {
        "first_name":   user.first_name or user.username,
        "org_name":     org_name or "your business",
        "confirm_url":  confirm_url,
        "site_url":     SITE,
    }
    html = render_to_string("emails/welcome.html", ctx)
    return _send(
        subject=f"Karibu Ziada POS, {ctx['first_name']}! Verify your email",
        to=user.email,
        html=html,
    )


# ── Email confirmation (resend) ────────────────────────────────────────────────

def send_confirmation_email(user) -> bool:
    """
    Send (or resend) just the email confirmation link.
    Safe to call multiple times — refreshes the token each time.
    """
    from .models import EmailVerificationToken

    token_obj, _ = EmailVerificationToken.objects.get_or_create(user=user)
    token_obj.token = __import__("uuid").uuid4()
    token_obj.created_at = timezone.now()
    token_obj.save(update_fields=["token", "created_at"])

    confirm_url = f"{SITE}/api/v1/auth/confirm-email/?token={token_obj.token}"
    ctx = {"email": user.email, "confirm_url": confirm_url, "site_url": SITE}
    html = render_to_string("emails/confirm_email.html", ctx)
    return _send(
        subject="Confirm your Ziada POS email address",
        to=user.email,
        html=html,
    )


# ── Daily sales report ─────────────────────────────────────────────────────────

def send_daily_sales_report(store=None) -> int:
    """
    Send the daily sales report email to the organisation owner.
    If `store` is None, send to ALL stores for ALL owners.

    Returns the number of emails successfully sent.
    """
    from apps.accounts.models import Store, User
    from apps.analytics.services import get_dashboard_data, get_payment_mix, get_kpi_summary

    if store is not None:
        stores = [store]
    else:
        stores = list(Store.objects.filter(is_active=True).select_related("organisation"))

    today   = date.today()
    sent    = 0

    for st in stores:
        # Find the owner's email
        owner = User.objects.filter(
            organisation=st.organisation,
            role="owner",
            is_active=True,
        ).first()

        if not owner or not owner.email:
            logger.warning("No owner email for store %s — skipping daily report.", st.name)
            continue

        # Pull dashboard data (reuses existing analytics service)
        try:
            dash = get_dashboard_data(st)
        except Exception as exc:
            logger.error("Failed to get dashboard data for store %s: %s", st.name, exc)
            continue

        kpis        = dash.get("kpis_today", {})
        payment_mix = dash.get("payment_mix", [])
        top_prods   = dash.get("top_products", [])
        low_stock   = dash.get("low_stock", [])
        credit_kpi  = dash.get("credit_kpi", {})

        revenue      = kpis.get("revenue", 0)
        profit       = kpis.get("profit", 0)
        margin_pct   = kpis.get("margin_pct", 0)
        txn_count    = kpis.get("transaction_count", 0)
        avg_ticket   = kpis.get("avg_ticket", 0)
        refund_total = kpis.get("refund_total", 0)
        rev_delta    = kpis.get("revenue_delta_pct")
        tax          = kpis.get("tax_collected", 0)
        cost         = revenue - profit - tax if revenue else 0

        # Format payment mix
        fmt_mix = [
            {
                "method":     m["method"],
                "pct":        round(m.get("pct", 0), 1),
                "amount_fmt": _fmt_tzs(m.get("amount", 0)),
            }
            for m in payment_mix
        ]

        # Format top products with bar %
        max_rev = top_prods[0]["revenue"] if top_prods else 1
        fmt_prods = [
            {
                "product_name": p["product_name"],
                "qty_sold":     p["qty_sold"],
                "revenue_fmt":  _fmt_tzs(p["revenue"]),
                "bar_pct":      round(p["revenue"] / max_rev * 100) if max_rev else 0,
            }
            for p in top_prods[:5]
        ]

        # Summary rows
        summary_rows = [
            {"label": "Revenue",    "value": _fmt_tzs(revenue),      "color": None},
            {"label": "Refunds",    "value": f"−{_fmt_tzs(refund_total)}", "color": "var(--bad)" if refund_total else None},
            {"label": "Net sales",  "value": _fmt_tzs(revenue - refund_total), "color": "#e2e8f0"},
            {"label": "Cost",       "value": f"−{_fmt_tzs(cost)}",   "color": None},
            {"label": "Gross profit","value": _fmt_tzs(profit),       "color": "#10b981"},
        ]

        ctx = {
            "store_name":       st.name,
            "report_date":      today.strftime("%a, %-d %b %Y"),
            "revenue":          _fmt_tzs(revenue),
            "profit":           _fmt_tzs(profit),
            "margin_pct":       round(margin_pct, 1),
            "transaction_count": txn_count,
            "avg_ticket":       _fmt_tzs(avg_ticket),
            "credit_total":     _fmt_tzs(credit_kpi.get("total", 0)),
            "credit_count":     credit_kpi.get("customer_count", 0),
            "revenue_delta":    rev_delta,
            "payment_mix":      fmt_mix,
            "top_products":     fmt_prods,
            "low_stock":        low_stock,
            "summary_rows":     summary_rows,
            "site_url":         SITE,
        }
        html = render_to_string("emails/daily_sales.html", ctx)

        ok = _send(
            subject=f"📊 Daily sales — {st.name} · {today.strftime('%-d %b')} · {_fmt_tzs(revenue)}",
            to=owner.email,
            html=html,
        )
        if ok:
            sent += 1

    return sent


# ── Scheduled report email ────────────────────────────────────────────────────

def send_scheduled_report(scheduled_report) -> dict:
    """
    Send a scheduled report email to all recipients.

    Generates the report data, builds an HTML summary email with key KPIs,
    and attaches a CSV of the data.

    Returns {"sent": int, "failed": int, "recipients": list[str]}.
    """
    from apps.reports.services import get_report_data, build_csv, parse_range_for_report

    sr   = scheduled_report
    store = sr.store
    recipients = [r for r in (sr.recipients or []) if r]

    if not recipients:
        logger.warning("Scheduled report %s has no recipients — skipped.", sr.id)
        return {"sent": 0, "failed": 0, "recipients": []}

    # Resolve date range from preset
    preset = sr.date_range_preset or "30d"
    start, end, period_label = parse_range_for_report({"range": preset})

    # Generate report data
    try:
        data = get_report_data(sr.report_type, store, start, end)
    except Exception as exc:
        logger.error("Scheduled report data generation failed for %s: %s", sr.id, exc)
        return {"sent": 0, "failed": len(recipients), "recipients": recipients}

    # Build CSV attachment
    try:
        csv_str, csv_filename = build_csv(sr.report_type, data)
    except Exception:
        csv_str, csv_filename = "", f"{sr.report_type}-report.csv"

    # Build KPI summary for email body
    report_names = {
        "sales":     "Sales Summary",
        "inventory": "Inventory Valuation",
        "tax":       "Tax Statement",
        "credit":    "Credit Aged Debtors",
    }
    report_name = report_names.get(sr.report_type, sr.report_type.title())

    # Extract a few headline numbers depending on report type
    highlights = []
    try:
        if sr.report_type == "sales":
            s = data.get("summary", {})
            highlights = [
                ("Total Revenue",     _fmt_tzs(s.get("total_revenue", 0))),
                ("Gross Profit",      _fmt_tzs(s.get("gross_profit", 0))),
                ("Transactions",      str(s.get("transaction_count", 0))),
                ("Avg Ticket",        _fmt_tzs(s.get("avg_ticket", 0))),
            ]
        elif sr.report_type == "inventory":
            s = data.get("summary", {})
            highlights = [
                ("Total SKUs",        str(s.get("total_skus", 0))),
                ("Retail Value",      _fmt_tzs(s.get("total_retail_value", 0))),
                ("Cost Value",        _fmt_tzs(s.get("total_cost_value", 0))),
                ("Low Stock Items",   str(s.get("low_stock_count", 0))),
            ]
        elif sr.report_type == "tax":
            s = data.get("summary", {})
            highlights = [
                ("Gross Sales",       _fmt_tzs(s.get("gross_sales", 0))),
                ("VAT Collected",     _fmt_tzs(s.get("tax_collected", 0))),
                ("Net (excl. VAT)",   _fmt_tzs(s.get("net_sales_excl_tax", 0))),
            ]
        elif sr.report_type == "credit":
            t = data.get("totals", {})
            highlights = [
                ("Total Outstanding", _fmt_tzs(t.get("total", 0))),
                ("Customers",         str(t.get("customer_count", 0))),
                ("Overdue Accounts",  str(t.get("overdue_count", 0))),
            ]
    except Exception:
        highlights = []

    ctx = {
        "report_name":    report_name,
        "store_name":     store.name,
        "period_label":   period_label,
        "highlights":     highlights,
        "csv_filename":   csv_filename if csv_str else "",
        "created_by_name": sr.created_by.get_full_name() or sr.created_by.email,
        "frequency_label": sr.get_frequency_display() if hasattr(sr, 'get_frequency_display') else sr.frequency.title(),
        "site_url":       SITE,
    }
    html = render_to_string("emails/scheduled_report.html", ctx)

    sent = failed = 0
    for email in recipients:
        try:
            msg = EmailMultiAlternatives(
                subject=f"[{store.name}] {report_name} — {period_label}",
                body=f"{report_name} for {store.name}, period: {period_label}.",
                from_email=FROM,
                to=[email],
            )
            msg.attach_alternative(html, "text/html")
            if csv_str:
                msg.attach(csv_filename, csv_str, "text/csv")
            msg.send(fail_silently=False)
            logger.info("Scheduled report '%s' sent to %s.", sr.id, email)
            sent += 1
        except Exception as exc:
            logger.error("Failed to send scheduled report to %s: %s", email, exc)
            failed += 1

    return {"sent": sent, "failed": failed, "recipients": recipients}


# ── Test email ────────────────────────────────────────────────────────────────

def send_test_email(to: str) -> bool:
    """
    Send a simple test email to verify ZohoMail SMTP is correctly configured.
    """
    ctx = {"site_url": SITE}
    html = render_to_string("emails/test_email.html", ctx)
    return _send(
        subject="Ziada POS — SMTP test successful",
        to=to,
        html=html,
    )

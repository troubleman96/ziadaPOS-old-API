import logging
from datetime import date, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)


def build_store_context(store) -> dict:
    from django.utils import timezone

    today = timezone.localdate()
    sources = []
    context = {
        "store_name":    store.name,
        "store_area":    store.area or "",
        "today":         today.strftime("%A, %B %d, %Y"),
    }

    try:
        from apps.transactions.models import Transaction
        from django.db.models import Count, Sum

        today_txns = Transaction.objects.filter(
            store=store,
            created_at__date=today,
            status=Transaction.STATUS_PAID,
        ).aggregate(
            revenue=Sum("total"),
            profit=Sum("profit"),
            count=Count("id"),
        )

        context["today_revenue"]   = today_txns["revenue"] or 0
        context["today_profit"]    = today_txns["profit"]  or 0
        context["today_txn_count"] = today_txns["count"]   or 0

        month_start = today.replace(day=1)
        month_txns = Transaction.objects.filter(
            store=store,
            created_at__date__gte=month_start,
            created_at__date__lte=today,
            status=Transaction.STATUS_PAID,
        ).aggregate(revenue=Sum("total"), profit=Sum("profit"), count=Count("id"))

        context["month_label"]       = today.strftime("%B %Y")
        context["month_revenue"]     = month_txns["revenue"] or 0
        context["month_profit"]      = month_txns["profit"]  or 0
        context["month_txn_count"]   = month_txns["count"]   or 0
        context["month_margin_pct"]  = (
            round(context["month_profit"] / context["month_revenue"] * 100, 1)
            if context["month_revenue"] else 0.0
        )

        from apps.expenses.models import Expense
        month_expenses = Expense.objects.filter(
            store=store, created_at__date__gte=month_start, created_at__date__lte=today,
        ).aggregate(total=Sum("amount"))
        context["month_expenses"] = month_expenses["total"] or 0
        context["month_net"] = context["month_profit"] - context["month_expenses"]

        sources.append("Sales data")

        recent = Transaction.objects.filter(store=store).order_by("-created_at")[:5]
        context["recent_txns"] = [
            {
                "txn_number":     t.txn_number,
                "total":          t.total,
                "payment_method": t.payment_method,
                "customer":       t.customer_name,
                "status":         t.status,
            }
            for t in recent
        ]

    except Exception as e:
        logger.warning("Failed to load sales context: %s", e)
        context["today_revenue"] = context["today_profit"] = context["today_txn_count"] = 0
        context["month_label"] = today.strftime("%B %Y")
        context["month_revenue"] = context["month_profit"] = context["month_txn_count"] = 0
        context["month_margin_pct"] = 0.0
        context["month_expenses"] = context["month_net"] = 0
        context["recent_txns"] = []

    try:
        from apps.inventory.models import Product

        low_stock = Product.objects.filter(
            store=store,
            is_active=True,
            stock__lte=models_F("min_stock"),
        ).values("name", "sku", "stock", "min_stock")[:10]

        context["low_stock_items"] = list(low_stock)
        sources.append("Inventory")

        top = Product.objects.filter(
            store=store, is_active=True
        ).order_by("-weekly_sold")[:5].values("name", "price", "weekly_sold", "stock")
        context["top_products"] = list(top)

    except Exception as e:
        logger.warning("Failed to load inventory context: %s", e)
        context["low_stock_items"] = []
        context["top_products"] = []

    try:
        from apps.customers.models import Customer

        customers_with_credit = Customer.objects.filter(
            store=store,
            is_active=True,
            open_credit__gt=0,
        ).values("name", "phone", "open_credit")[:10]

        context["customers_with_credit"] = list(customers_with_credit)
        total_outstanding = sum(c["open_credit"] for c in context["customers_with_credit"])
        context["total_outstanding_credit"] = total_outstanding
        sources.append("Credits")

    except Exception as e:
        logger.warning("Failed to load credits context: %s", e)
        context["customers_with_credit"] = []
        context["total_outstanding_credit"] = 0

    context["sources"] = sources
    return context


def _fmt_tzs(amount: int) -> str:
    return f"TZS {amount:,}"


def build_system_prompt(store) -> tuple[str, list[str]]:
    ctx = build_store_context(store)
    sources = ctx.get("sources", [])

    low_stock_text = ""
    if ctx["low_stock_items"]:
        lines = [
            f"  - {item['name']} ({item['sku']}): {item['stock']} left (min: {item['min_stock']})"
            for item in ctx["low_stock_items"]
        ]
        low_stock_text = "LOW STOCK ITEMS (need restocking):\n" + "\n".join(lines)
    else:
        low_stock_text = "LOW STOCK ITEMS: None \u2014 all products sufficiently stocked."

    credit_text = ""
    if ctx["customers_with_credit"]:
        lines = [
            f"  - {c['name']} ({c['phone']}): outstanding {_fmt_tzs(c['open_credit'])}"
            for c in ctx["customers_with_credit"]
        ]
        credit_text = (
            f"OUTSTANDING CREDIT \u2014 Total: {_fmt_tzs(ctx['total_outstanding_credit'])}\n"
            + "Customers with open balances:\n"
            + "\n".join(lines)
        )
    else:
        credit_text = "OUTSTANDING CREDIT: No open credit tabs."

    top_products_text = ""
    if ctx.get("top_products"):
        lines = [
            f"  - {p['name']}: {_fmt_tzs(p['price'])}/unit, {p['weekly_sold']} sold/week, {p['stock']} in stock"
            for p in ctx["top_products"]
        ]
        top_products_text = "TOP SELLING PRODUCTS (by weekly units):\n" + "\n".join(lines)

    prompt = f"""You are Ziada AI \u2014 a business intelligence assistant for African retail shops.
You are talking to a staff member of **{ctx['store_name']}** ({ctx['store_area']}).
Today is {ctx['today']}.

YOUR PERSONA:
- Helpful, concise, and business-focused
- Fluent in both Swahili and English \u2014 respond in the same language the user writes in
- Use simple, clear language \u2014 not overly technical
- Address specific products, customers, and numbers from the data below
- Sign off as "Ziada AI" when needed

LIVE STORE DATA (as of right now):
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

TODAY'S PERFORMANCE ({ctx['today']}):
  - Revenue (paid sales): {_fmt_tzs(ctx['today_revenue'])}
  - Gross profit: {_fmt_tzs(ctx['today_profit'])}
  - Transactions completed: {ctx['today_txn_count']}

MONTH-TO-DATE ({ctx['month_label']}, 1st through today):
  - Revenue: {_fmt_tzs(ctx['month_revenue'])}
  - Gross profit: {_fmt_tzs(ctx['month_profit'])} ({ctx['month_margin_pct']}% margin)
  - Transactions: {ctx['month_txn_count']}
  - Operating expenses recorded: {_fmt_tzs(ctx['month_expenses'])}
  - Net (profit − expenses): {_fmt_tzs(ctx['month_net'])}

{low_stock_text}

{credit_text}

{top_products_text}

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

RESPONSE RULES:
1. ALWAYS ground your answers in the actual data above \u2014 never make up numbers
2. Use markdown formatting: **bold** for numbers/names, bullet lists \u2014 avoid tables, they render poorly in this chat UI
3. Be concise \u2014 aim for 3-5 short paragraphs max unless a detailed breakdown is requested
4. If asked to draft a message (WhatsApp, SMS), draft it in Swahili and provide the English translation
5. If data is missing or unclear, say so \u2014 don't invent
6. For financial advice (pricing, reordering), be concrete: give specific numbers from the data
7. Tanzania context: currency is TZS (Tanzanian Shilling), VAT is 18%, M-Pesa is most common payment
8. Answer the specific question asked \u2014 never reply with a generic greeting or a menu of what you "can help with"; that only applies to the very first message of a brand-new conversation
9. Stay scoped to this shop: sales, inventory, customers, credit, staff, and expenses. Politely decline unrelated requests (general trivia, coding help, topics with no connection to running this shop) and redirect to what you can help with here"""

    return prompt, sources


def call_ngamia(messages: list[dict], system_prompt: str, api_key: str = None) -> dict:
    """
    Call the Ngamia AI gateway with a list of messages.

    Ngamia is an OpenAI-compatible API gateway (https://api.ngamia.cc/v1).
    Uses the openai Python SDK with a custom base_url.

    `api_key` overrides the platform key — used when an organisation has
    exhausted its free monthly credits and pasted its own Ngamia key
    (Organisation.ngamia_api_key) to keep going on its own balance.
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key or settings.NGAMIA_API_KEY,
            base_url=settings.NGAMIA_BASE_URL,
        )

        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = client.chat.completions.create(
            model=settings.NGAMIA_MODEL,
            messages=full_messages,
            max_tokens=1500,
            temperature=0.7,
        )

        choice = response.choices[0]
        usage  = response.usage

        return {
            "success":           True,
            "content":           choice.message.content,
            "model":             response.model,
            "prompt_tokens":     usage.prompt_tokens     if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
        }

    except Exception as exc:
        logger.exception("Ngamia API call failed: %s", exc)
        return {
            "success": False,
            "error":   str(exc),
        }


def chat(conversation, user_message_content: str) -> "Message":
    from apps.accounts.models import AICredit

    from .models import Message

    organisation = conversation.organisation
    ai_credit = AICredit.get_or_create_current(organisation)

    # Free platform credits exhausted. If the org has pasted their own Ngamia
    # key (Settings \u2192 Integrations), keep going unmetered on their own balance
    # instead of blocking \u2014 otherwise show the exhausted-credits fallback.
    using_own_key = False
    if ai_credit.remaining <= 0:
        if organisation.ngamia_api_key:
            using_own_key = True
        else:
            fallback = Message.objects.create(
                conversation=conversation,
                role=Message.ROLE_ASSISTANT,
                content=(
                    "Samahani \u2014 AI credits za shirika lako zimekwisha kwa mwezi huu. "
                    "Unaweza kubandika Ngamia API key yako mwenyewe (Settings \u2192 Integrations) "
                    "ili uendelee kutumia bila kikomo, au wasiliana na msimamizi wako.\n\n"
                    "_Sorry \u2014 your organisation's free AI credits are exhausted for this month. "
                    "Paste your own Ngamia API key in Settings \u2192 Integrations to keep going "
                    "unlimited on your own balance, or contact your admin._"
                ),
                sources_used="",
            )
            return fallback

    user_msg = Message.objects.create(
        conversation=conversation,
        role=Message.ROLE_USER,
        content=user_message_content.strip(),
    )

    if not conversation.first_message_preview:
        conversation.first_message_preview = user_message_content[:200]
        title = user_message_content.strip()[:60]
        conversation.title = title if title else "New conversation"
        conversation.save(update_fields=["first_message_preview", "title", "updated_at"])

    system_prompt, sources = build_system_prompt(conversation.store)

    history = list(
        Message.objects.filter(
            conversation=conversation,
            role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT],
        ).order_by("-created_at")[:10]
    )
    history.reverse()

    messages_for_api = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]

    result = call_ngamia(
        messages_for_api, system_prompt,
        api_key=organisation.ngamia_api_key if using_own_key else None,
    )

    if not result["success"]:
        err_msg = Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_ASSISTANT,
            content=(
                "Samahani, kulikuwa na hitilafu ya kiufundi. Tafadhali jaribu tena.\n\n"
                "_Sorry, there was a technical error. Please try again._"
            ),
        )
        logger.error("AI response failed for conversation %s: %s", conversation.id, result.get("error"))
        return err_msg

    assistant_msg = Message.objects.create(
        conversation=conversation,
        role=Message.ROLE_ASSISTANT,
        content=result["content"],
        model_used=result.get("model", settings.NGAMIA_MODEL),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        sources_used=",".join(sources),
    )

    # Only deduct from the free platform allowance when it was actually used —
    # calls made on the org's own Ngamia key don't count against it.
    if not using_own_key:
        try:
            ai_credit.used += 1
            ai_credit.save(update_fields=["used", "updated_at"])
        except Exception as exc:
            logger.warning("Failed to deduct AI credit: %s", exc)

    from django.utils import timezone
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["updated_at"])

    logger.info(
        "AI chat: conversation=%s user=%s tokens=%s",
        conversation.id,
        conversation.user.username,
        result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
    )

    return assistant_msg


def models_F(field_name):
    from django.db.models import F
    return F(field_name)

"""
apps/ai/service.py

OpenRouter AI service for Ziada AI assistant.

This is the core of the /ai feature:
  1. build_store_context(store)   → assembles live store data into a structured text
  2. build_system_prompt(store)   → creates the system prompt with store context injected
  3. call_openrouter(messages)    → calls OpenRouter API via the openai SDK
  4. chat(conversation, user_msg) → end-to-end: save user msg, call AI, save response

Why OpenRouter?
  - Unified API gateway for multiple LLM providers
  - GPT-4o-mini for MVP: fast, cheap, multilingual (Swahili + English), JSON-capable
  - Easy swap to Claude, Gemini, etc. by changing model ID
  - Uses the openai Python SDK with a custom base_url

Store context approach:
  Instead of expensive RAG/vector search for MVP, we inject a structured
  text summary of the store's live data directly into the system prompt.
  This keeps it simple, fast, and accurate for small-to-medium stores.
  The context covers: today's KPIs, low-stock items, overdue credits,
  top-selling products, and recent transactions.

Credit deduction:
  Each successful AI response deducts 1 credit from AICredit.used.
  If credits are exhausted, chat() returns a fallback message without
  calling the API (to prevent unexpected charges).
"""

import logging
from datetime import date, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Store Context Builder ─────────────────────────────────────────────────────

def build_store_context(store) -> dict:
    """
    Build a structured dict of live store data for the AI system prompt.

    Pulls from:
      - Recent transactions (today's revenue, transaction count)
      - Inventory (low-stock items)
      - Credits (outstanding balances, overdue customers)
      - Analytics (DailySummary if available)

    Returns a dict with:
      {
        "store_name":       "Duka Kuu",
        "today_revenue":    1842000,
        "today_txn_count":  87,
        "low_stock_items":  [...],
        "overdue_credits":  [...],
        "recent_txns":      [...],
        "top_products":     [...],
        "sources":          ["Sales data", "Inventory", "Credits"],
      }

    The dict is then formatted into the system prompt as structured text.
    """
    from django.utils import timezone

    today = timezone.now().date()
    sources = []
    context = {
        "store_name":    store.name,
        "store_area":    store.area or "",
        "today":         today.strftime("%A, %B %d, %Y"),
    }

    # ── Today's sales ─────────────────────────────────────────────────────────
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
        sources.append("Sales data")

        # Recent transactions (last 5) for context
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
        context["recent_txns"] = []

    # ── Inventory / Low stock ─────────────────────────────────────────────────
    try:
        from apps.inventory.models import Product

        low_stock = Product.objects.filter(
            store=store,
            is_active=True,
            stock__lte=models_F("min_stock"),
        ).values("name", "sku", "stock", "min_stock")[:10]

        context["low_stock_items"] = list(low_stock)
        sources.append("Inventory")

        # Top products by weekly_sold
        top = Product.objects.filter(
            store=store, is_active=True
        ).order_by("-weekly_sold")[:5].values("name", "price", "weekly_sold", "stock")
        context["top_products"] = list(top)

    except Exception as e:
        logger.warning("Failed to load inventory context: %s", e)
        context["low_stock_items"] = []
        context["top_products"] = []

    # ── Outstanding credits ───────────────────────────────────────────────────
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
    """Format an integer as 'TZS 1,234,000'."""
    return f"TZS {amount:,}"


def build_system_prompt(store) -> tuple[str, list[str]]:
    """
    Build the system prompt for the AI with live store context injected.

    Returns:
      (system_prompt: str, sources: list[str])

    The system prompt:
      1. Defines the AI's persona and language preferences
      2. Injects live store data (today's KPIs, low stock, credits)
      3. Sets rules for response format
    """
    ctx = build_store_context(store)
    sources = ctx.get("sources", [])

    # ── Format store data as structured text ──────────────────────────────────
    low_stock_text = ""
    if ctx["low_stock_items"]:
        lines = [
            f"  - {item['name']} ({item['sku']}): {item['stock']} left (min: {item['min_stock']})"
            for item in ctx["low_stock_items"]
        ]
        low_stock_text = "LOW STOCK ITEMS (need restocking):\n" + "\n".join(lines)
    else:
        low_stock_text = "LOW STOCK ITEMS: None — all products sufficiently stocked."

    credit_text = ""
    if ctx["customers_with_credit"]:
        lines = [
            f"  - {c['name']} ({c['phone']}): outstanding {_fmt_tzs(c['open_credit'])}"
            for c in ctx["customers_with_credit"]
        ]
        credit_text = (
            f"OUTSTANDING CREDIT — Total: {_fmt_tzs(ctx['total_outstanding_credit'])}\n"
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

    # ── Build the full system prompt ──────────────────────────────────────────
    prompt = f"""You are Ziada AI — a business intelligence assistant for African retail shops.
You are talking to a staff member of **{ctx['store_name']}** ({ctx['store_area']}).
Today is {ctx['today']}.

YOUR PERSONA:
- Helpful, concise, and business-focused
- Fluent in both Swahili and English — respond in the same language the user writes in
- Use simple, clear language — not overly technical
- Address specific products, customers, and numbers from the data below
- Sign off as "Ziada AI" when needed

LIVE STORE DATA (as of right now):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TODAY'S PERFORMANCE ({ctx['today']}):
  - Revenue (paid sales): {_fmt_tzs(ctx['today_revenue'])}
  - Gross profit: {_fmt_tzs(ctx['today_profit'])}
  - Transactions completed: {ctx['today_txn_count']}

{low_stock_text}

{credit_text}

{top_products_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESPONSE RULES:
1. ALWAYS ground your answers in the actual data above — never make up numbers
2. Use markdown formatting: **bold** for numbers/names, bullet lists, tables
3. Be concise — aim for 3-5 short paragraphs max unless a detailed breakdown is requested
4. If asked to draft a message (WhatsApp, SMS), draft it in Swahili and provide the English translation
5. If data is missing or unclear, say so — don't invent
6. For financial advice (pricing, reordering), be concrete: give specific numbers from the data
7. Tanzania context: currency is TZS (Tanzanian Shilling), VAT is 18%, M-Pesa is most common payment"""

    return prompt, sources


# ── OpenRouter API Call ───────────────────────────────────────────────────────

def call_openrouter(messages: list[dict], system_prompt: str) -> dict:
    """
    Call OpenRouter with a list of messages and return the response dict.

    Args:
      messages:      List of {"role": "user"|"assistant", "content": "..."}
                     (conversation history, newest last)
      system_prompt: The pre-built system prompt with store context

    Returns:
      {
        "content":           "AI response text",
        "model":             "openai/gpt-4o-mini",
        "prompt_tokens":     123,
        "completion_tokens": 456,
        "success":           True,
      }

    On failure, returns {"success": False, "error": "..."}.

    Uses the openai Python SDK with OpenRouter's base_url.
    OpenRouter is API-compatible with the OpenAI SDK.
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                # OpenRouter requests these for routing and rate-limiting
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-Title":      "Ziada POS AI",
            },
        )

        # Build the full message list: system first, then history
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
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
        logger.exception("OpenRouter API call failed: %s", exc)
        return {
            "success": False,
            "error":   str(exc),
        }


# ── End-to-end Chat ───────────────────────────────────────────────────────────

def chat(conversation, user_message_content: str) -> "Message":
    """
    Process one turn of a conversation:
      1. Check AI credits — return fallback if exhausted
      2. Save the user's message
      3. Build system prompt with live store context
      4. Gather conversation history (last 10 messages for context window)
      5. Call OpenRouter API
      6. Save the assistant's response
      7. Deduct 1 AI credit
      8. Update conversation title (first message only)

    Returns the newly created assistant Message object.

    Raises:
      ValueError: if AI credits are exhausted
    """
    from apps.accounts.models import AICredit

    from .models import Message

    # ── 1. Check AI credits ───────────────────────────────────────────────────
    ai_credit = AICredit.get_or_create_current(conversation.organisation)
    if ai_credit.remaining <= 0:
        # Return a friendly fallback message without calling the API
        fallback = Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_ASSISTANT,
            content=(
                "Samahani — AI credits za shirika lako zimekwisha kwa mwezi huu. "
                "Tafadhali wasiliana na msimamizi wako ili upate credits zaidi.\n\n"
                "_Sorry — your organisation's AI credits are exhausted for this month. "
                "Please contact your admin to get more credits._"
            ),
            sources_used="",
        )
        return fallback

    # ── 2. Save user message ──────────────────────────────────────────────────
    user_msg = Message.objects.create(
        conversation=conversation,
        role=Message.ROLE_USER,
        content=user_message_content.strip(),
    )

    # Update conversation preview from first user message
    if not conversation.first_message_preview:
        conversation.first_message_preview = user_message_content[:200]
        # Auto-title: first 60 chars of first message (cleaned up)
        title = user_message_content.strip()[:60]
        conversation.title = title if title else "New conversation"
        conversation.save(update_fields=["first_message_preview", "title", "updated_at"])

    # ── 3. Build system prompt ────────────────────────────────────────────────
    system_prompt, sources = build_system_prompt(conversation.store)

    # ── 4. Gather conversation history ────────────────────────────────────────
    # Use last 10 messages (5 turns) to keep context window manageable
    history = list(
        Message.objects.filter(
            conversation=conversation,
            role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT],
        ).order_by("-created_at")[:10]
    )
    history.reverse()  # oldest first

    messages_for_api = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]

    # ── 5. Call OpenRouter API ────────────────────────────────────────────────
    result = call_openrouter(messages_for_api, system_prompt)

    if not result["success"]:
        # Save a generic error message so the conversation doesn't break
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

    # ── 6. Save assistant message ─────────────────────────────────────────────
    assistant_msg = Message.objects.create(
        conversation=conversation,
        role=Message.ROLE_ASSISTANT,
        content=result["content"],
        model_used=result.get("model", settings.OPENROUTER_MODEL),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        sources_used=",".join(sources),
    )

    # ── 7. Deduct AI credit ───────────────────────────────────────────────────
    try:
        ai_credit.used += 1
        ai_credit.save(update_fields=["used", "updated_at"])
    except Exception as exc:
        logger.warning("Failed to deduct AI credit: %s", exc)

    # ── 8. Touch conversation updated_at ──────────────────────────────────────
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


# ── Helper: F expression import for inventory filter ─────────────────────────
def models_F(field_name):
    """Return a Django F() expression. Defined here to avoid top-level import."""
    from django.db.models import F
    return F(field_name)

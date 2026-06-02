# apps/ai — Ziada AI Assistant

## What this app does

`apps/ai` implements the AI chat feature of Ziada POS. It connects to OpenRouter (an LLM gateway) using the OpenAI SDK, builds a system prompt that includes live store data, and maintains a persistent conversation history in the database.

The AI assistant answers questions in Swahili or English about the store's own data: "Nionyeshe mauzo ya leo" ("Show me today's sales"), "Which products need restocking?", "Draft a WhatsApp reminder for Fatuma about her debt."

**UI page this app powers:**
- `/ai` — full-page AI chat interface:
  - Left sidebar: conversation history list (newest first)
  - Main panel: message thread (user + assistant turns)
  - Input bar: send a new message
  - Source chips: shows which data sources were loaded (Sales data, Inventory, Credits)
  - AI credit meter: remaining credits for the month

**AppConfig note:** The Django app label is `"ai_app"` (not `"ai"`) to avoid collision with the Python standard library's `ai` namespace. This is why `INSTALLED_APPS` contains `"apps.ai.apps.AIConfig"` instead of just `"apps.ai"`.

---

## Models

### `Conversation`

One AI chat conversation thread. Multiple conversations per user, shown in the sidebar.

| Field | Type | Description |
|-------|------|-------------|
| `user` | FK → User (CASCADE) | Staff member who started this conversation. |
| `store` | FK → Store (CASCADE) | Store whose data is in scope for this conversation. |
| `organisation` | FK → Organisation (CASCADE) | For AI credit billing. |
| `title` | CharField(200) | Auto-generated from the first user message (first 60 chars). Default: "New conversation". |
| `first_message_preview` | CharField(200) | First 200 chars of the first user message. Shown in the sidebar under the title. |
| `is_active` | BooleanField | `False` = archived, hidden from sidebar. |
| `created_at` / `updated_at` | DateTimeField | `updated_at` is touched on every new message to keep the conversation at the top of the sidebar list. |

**DB table:** `ai_app_conversation`
**Ordering:** `["-updated_at"]` — most recently active first.
**DB index:** `(user, is_active, updated_at)` — used by `ConversationListView`.

**Computed property:**
```python
conversation.message_count  # int: total messages in this conversation
```

---

### `Message`

A single message within a conversation.

**Role values:**
- `user` — text sent by the staff member
- `assistant` — response from the LLM via OpenRouter
- `system` — stored for debug purposes; not shown to users

| Field | Type | Description |
|-------|------|-------------|
| `conversation` | FK → Conversation (CASCADE) | Parent conversation. |
| `role` | CharField(20) | `user` / `assistant` / `system` |
| `content` | TextField | Message text. Supports Markdown. Swahili or English. |
| `model_used` | CharField(100) | Model ID from OpenRouter (e.g. `openai/gpt-4o-mini`). Empty for user messages. |
| `prompt_tokens` | PositiveIntegerField | Tokens consumed by the prompt. For cost tracking. |
| `completion_tokens` | PositiveIntegerField | Tokens in the assistant's response. |
| `sources_used` | CharField(500) | Comma-separated list of data sources loaded into context (e.g. `"Sales data,Inventory,Credits"`). |

**DB table:** `ai_app_message`
**Ordering:** `["created_at"]` — chronological (oldest first, for display as a thread).

**Computed property:**
```python
message.sources_list  # list[str]: ["Sales data", "Inventory", "Credits"]
```

---

## Service (`service.py`)

The AI service has four main functions:

### `build_store_context(store) → dict`

Assembles live store data from the database into a structured Python dict. This is the "context" that gets injected into the AI system prompt.

Pulls from:
- **Transactions:** today's revenue, profit, transaction count, last 5 recent transactions
- **Inventory:** products at or below `min_stock` (up to 10), top 5 products by `weekly_sold`
- **Customers/Credits:** up to 10 customers with `open_credit > 0`

Returns:
```python
{
  "store_name": "Duka Kuu",
  "store_area": "Mwanza",
  "today": "Tuesday, May 26, 2026",
  "today_revenue": 842000,
  "today_profit": 147350,
  "today_txn_count": 23,
  "recent_txns": [...],
  "low_stock_items": [...],
  "top_products": [...],
  "customers_with_credit": [...],
  "total_outstanding_credit": 850000,
  "sources": ["Sales data", "Inventory", "Credits"],
}
```

Each data section is wrapped in a `try/except` — if one data source fails (e.g. no transactions table yet), it returns an empty default rather than crashing the whole context build.

---

### `build_system_prompt(store) → tuple[str, list[str]]`

Formats the `build_store_context` output into a rich text system prompt. Returns `(prompt_text, sources_list)`.

The prompt includes:
1. AI persona: "You are Ziada AI — a business intelligence assistant for African retail shops"
2. Store identity: name, area, today's date
3. Live store data formatted as structured text (low stock items, credit customers, top products)
4. Response rules: ground answers in actual data, use Markdown, respond in the user's language, Tanzania-specific context (TZS currency, 18% VAT, M-Pesa)

**Language handling:** The AI is instructed to respond in the same language the user writes in (Swahili or English). No explicit language detection is done — the LLM handles this natively.

---

### `call_openrouter(messages, system_prompt) → dict`

Calls the OpenRouter API via the `openai` Python SDK with a custom `base_url`:

```python
from openai import OpenAI
client = OpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": settings.OPENROUTER_SITE_URL,
        "X-Title": "Ziada POS AI",
    },
)
```

Parameters: `max_tokens=1500`, `temperature=0.7`.

Returns:
```python
{
  "success": True,
  "content": "Response text...",
  "model": "openai/gpt-4o-mini",
  "prompt_tokens": 1247,
  "completion_tokens": 312,
}
```

On failure, returns `{"success": False, "error": "..."}` — the `chat()` function handles this gracefully by saving a generic error message.

---

### `chat(conversation, user_message_content) → Message`

End-to-end conversation turn:

1. **Check AI credits** — if `ai_credit.remaining <= 0`, return a friendly fallback message in Swahili + English without calling the API
2. **Save user message** to DB
3. Update `conversation.first_message_preview` and auto-title (first turn only)
4. **Build system prompt** from live store data
5. **Gather conversation history** — last 10 messages (5 turns) to keep context window manageable
6. **Call OpenRouter** via `call_openrouter()`
7. If call fails: save a generic error message and return it
8. **Save assistant message** with token counts and sources_used
9. **Deduct 1 AI credit** from `AICredit.used`
10. Touch `conversation.updated_at`

Returns the newly created assistant `Message` object.

---

## API Endpoints

All routes mount at `/api/v1/ai/`.

### `GET /conversations/`

**View:** `ConversationListView`
**Auth:** `IsAuthenticated`

Returns all active conversations for the authenticated user in their store, ordered newest-first. Used to populate the sidebar.

Response: list of `ConversationListSerializer` data (id, title, first_message_preview, updated_at, message_count).

---

### `POST /chat/`

**View:** `StartChatView`
**Auth:** `IsAuthenticated`

Start a new conversation and get the first AI reply.

```json
{ "message": "Habari, nionyeshe mauzo ya leo" }
```

Response (201):
```json
{
  "conversation_id": "uuid",
  "message": {
    "id": "uuid",
    "role": "assistant",
    "content": "Habari! Leo...",
    "model_used": "openai/gpt-4o-mini",
    "prompt_tokens": 1247,
    "completion_tokens": 312,
    "sources_list": ["Sales data", "Inventory"],
    "created_at": "..."
  }
}
```

The frontend redirects to `/ai?c={conversation_id}` after receiving this response.

---

### `GET /conversations/{id}/`

Full conversation with all messages. Used when loading an existing conversation from the sidebar.

---

### `PATCH /conversations/{id}/`

Rename or archive a conversation.

```json
{ "title": "Sales review May 26" }
{ "is_active": false }
```

---

### `POST /conversations/{id}/chat/`

**View:** `ContinueChatView`
**Auth:** `IsAuthenticated`

Continue an existing conversation.

```json
{ "message": "Niambie zaidi kuhusu Sukari" }
```

Returns the new assistant `Message` only (not the full conversation).

---

### `GET /suggestions/`

**View:** `AISuggestionsView`
**Auth:** `IsAuthenticated`

Returns contextual suggested prompt chips for the `/ai` page input area. Dynamic suggestions based on current store state:

- If low-stock items exist → "Bidhaa N zinahitaji kununuliwa — nionyeshe"
- If customers have open credit → "Hali ya madeni — wateja N wana deni"
- Always included: sales analysis, profit analysis, today's report, sales forecast

Also returns the AI credit meter:
```json
{
  "suggestions": [...],
  "ai_credits": {
    "remaining": 47,
    "used": 53,
    "allocated": 100,
    "pct_used": 53.0
  }
}
```

---

## AI Credits

Each successful AI response deducts 1 credit from `AICredit.used` (model in `apps.accounts`). Credits are allocated monthly per Organisation.

When `ai_credit.remaining <= 0`, the `chat()` function returns a friendly bilingual message without calling the API:

```
Samahani — AI credits za shirika lako zimekwisha kwa mwezi huu.
Tafadhali wasiliana na msimamizi wako ili upate credits zaidi.

Sorry — your organisation's AI credits are exhausted for this month.
Please contact your admin to get more credits.
```

The `AICredit` model in `apps/accounts` has a `get_or_create_current(organisation)` classmethod that finds or creates the current month's credit record.

---

## Configuration (`settings/base.py`)

| Setting | Description | Default |
|---------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (from `.env`) | `""` |
| `OPENROUTER_MODEL` | LLM model ID | `"openai/gpt-4o-mini"` |
| `OPENROUTER_BASE_URL` | OpenRouter endpoint | `"https://openrouter.ai/api/v1"` |
| `OPENROUTER_SITE_URL` | Sent as `HTTP-Referer` header | `"http://localhost:3000"` |
| `OPENROUTER_SITE_NAME` | Sent as `X-Title` header | `"Ziada POS"` |
| `AI_MAX_CONTEXT_TOKENS` | Max tokens for context window | `4000` |

**OpenRouter is API-compatible with the OpenAI SDK.** Changing the model is as simple as updating `OPENROUTER_MODEL` in `.env`. The current default (`openai/gpt-4o-mini`) is fast, cheap (~$0.15/1M input tokens), and has strong multilingual capability for Swahili/English.

---

## Design Decisions

**Why OpenRouter instead of direct OpenAI API?**
OpenRouter is an API gateway that supports dozens of LLMs (GPT-4o-mini, Claude, Gemini, Llama, Mistral) via a single unified endpoint. Changing the AI model is a one-line `.env` change, not a code change. This is valuable for a multi-market product where different customers may prefer different models.

**Why store messages in the database?**
1. Conversation history sidebar — users can resume conversations across sessions and devices
2. Audit trail — AI responses are logged with timestamps and token counts
3. Future feedback loop — thumbs up/down data can be added to `Message` for fine-tuning
4. Cost visibility — `prompt_tokens + completion_tokens` per message enables exact cost attribution

**Why inject store context in the system prompt instead of RAG/vector search?**
For MVP with small-to-medium stores, structured context injection is:
- Simpler to implement (no vector DB infrastructure)
- More reliable (deterministic, not similarity-based)
- Faster (no vector search latency)
- More accurate (exact numbers, not approximately similar text)

A typical store context is ~800-1200 tokens — well within GPT-4o-mini's 128k context window. Vector search would be worth considering when context grows beyond ~10k tokens (very large stores with thousands of products and customers).

**Why limit conversation history to 10 messages?**
GPT-4o-mini supports 128k tokens, but including the full conversation history in every request increases cost and latency. 10 messages (5 user + 5 assistant turns) provides enough context for continuity without excessive cost. The system prompt (~1500 tokens) + history (~2000 tokens) + response (~500 tokens) comfortably fits within the model's window.

---

## Common Gotchas

1. **The `apps.ai.apps.AIConfig` label is `"ai_app"`.** Django uses this label as the prefix for model DB tables (`ai_app_conversation`, `ai_app_message`) and for reverse relations. Don't use `"ai"` as the label — it conflicts with Python's `ai` namespace.

2. **`OPENROUTER_API_KEY` must be set in `.env`.** If empty, `call_openrouter()` will fail with an authentication error. The `chat()` function catches this and returns a generic error message, but the `/ai` page will appear to work but always return "technical error" responses.

3. **AI credit deduction happens AFTER the response is saved.** If the credit deduction fails (e.g. DB error), the response is still returned to the user. The credits may be undercounted. This is intentional — failing the response because of a credit accounting error would be a worse user experience.

4. **Conversation history only includes `user` and `assistant` roles.** `system` messages (if any exist in the DB for debugging) are excluded from the history sent to the API to avoid confusing the model.

5. **`build_store_context` catches all exceptions per data source.** If `apps.inventory` is somehow unavailable, the inventory section of the context is silently empty rather than crashing the whole chat. Check logs for `"Failed to load inventory context"` warnings if the AI doesn't mention inventory data when it should.

6. **`conversation.updated_at` is manually set at the end of `chat()`.** Django's `auto_now` field is updated via `save()`, but since we call `save(update_fields=["updated_at"])`, the `auto_now` behavior fires. However, this is explicit to ensure the timestamp is correct even if the `save()` call pattern changes.

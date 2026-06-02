"""
apps/ai/models.py

Models for the Ziada AI assistant.

Conversation model:
  Each conversation belongs to a user and a store.
  The title is auto-generated from the first user message.
  Conversations are listed in the /ai sidebar.

Message model:
  Each message in a conversation has a role (user/assistant) and content.
  Assistant messages also store: model used, prompt tokens, completion tokens
  (for cost tracking and debugging).

Why store messages in DB?
  - Conversation history sidebar in the /ai page
  - Resume conversations across sessions / devices
  - Audit trail for AI responses
  - Future: feedback loop (thumbs up/down) to improve responses

Why store tokens?
  - Track AI credit consumption per message
  - Feed into the AICredit.used counter in the accounts app
  - Help identify expensive conversations that could be optimised
"""

from django.db import models

from apps.accounts.models import Organisation, Store, User
from apps.core.models import BaseModel


class Conversation(BaseModel):
    """
    A single AI chat conversation.

    Each conversation is a thread of messages between a user and Ziada AI.
    Multiple conversations are shown in the sidebar history on /ai.

    Table: ai_app_conversation
    """

    # The user who started this conversation (cashier, manager, or admin)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
        help_text="Staff member who started this conversation.",
    )

    # Store context for this conversation — all AI responses are scoped to this store
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
        help_text="Store whose data is available to the AI in this conversation.",
    )

    # Organisation (for AI credit tracking)
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
        help_text="Organisation for AI credit billing.",
    )

    # Auto-generated from the first user message
    # Default: "New conversation" → updated after first reply
    title = models.CharField(
        max_length=200,
        default="New conversation",
        help_text="Short title auto-generated from the first message.",
    )

    # Snapshot of the first user message (shown in the sidebar)
    first_message_preview = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="First 200 chars of the first user message (for sidebar display).",
    )

    # Allow users to archive old conversations
    is_active = models.BooleanField(
        default=True,
        help_text="Archived conversations are hidden from the sidebar.",
    )

    class Meta:
        """Meta options for Conversation."""
        db_table = "ai_app_conversation"
        ordering = ["-updated_at"]
        verbose_name = "AI Conversation"
        verbose_name_plural = "AI Conversations"
        indexes = [
            models.Index(fields=["user", "is_active", "updated_at"], name="idx_conv_user_active"),
        ]

    def __str__(self):
        return f"Convo '{self.title}' — {self.user.username} ({self.store.name})"

    @property
    def message_count(self) -> int:
        """Number of messages in this conversation."""
        return self.messages.count()


class Message(BaseModel):
    """
    A single message within an AI conversation.

    Can be:
      - role='user'      → text sent by the staff member
      - role='assistant' → response from OpenRouter GPT-4o-mini

    Token counts are stored for AI credit accounting and debugging.

    Table: ai_app_message
    """

    # ── Role choices ──────────────────────────────────────────────────────────
    ROLE_USER      = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM    = "system"   # Stored for debug; not shown to users

    ROLE_CHOICES = [
        (ROLE_USER,      "User"),
        (ROLE_ASSISTANT, "Assistant"),
        (ROLE_SYSTEM,    "System"),
    ]

    # ── Relationships ─────────────────────────────────────────────────────────

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="Conversation this message belongs to.",
    )

    # ── Content ───────────────────────────────────────────────────────────────

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        help_text="Who sent this message.",
    )

    content = models.TextField(
        help_text="Message text (Swahili or English, supports markdown).",
    )

    # ── LLM metadata (assistant messages only) ────────────────────────────────

    # Which model generated this response
    model_used = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Model ID from OpenRouter (e.g. 'openai/gpt-4o-mini').",
    )

    # Token usage for cost tracking
    prompt_tokens     = models.PositiveIntegerField(default=0, help_text="Tokens in the prompt.")
    completion_tokens = models.PositiveIntegerField(default=0, help_text="Tokens in the completion.")

    # Data sources used to build the context (shown as chips in the UI)
    # Stored as a comma-separated list: "Sales data,Inventory,Credits"
    sources_used = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Comma-separated list of data sources injected into context.",
    )

    class Meta:
        """Meta options for Message."""
        db_table = "ai_app_message"
        ordering = ["created_at"]  # Messages in chronological order
        verbose_name = "AI Message"
        verbose_name_plural = "AI Messages"

    def __str__(self):
        preview = self.content[:60] + ("…" if len(self.content) > 60 else "")
        return f"[{self.role.upper()}] {preview}"

    @property
    def sources_list(self) -> list[str]:
        """Return sources_used as a Python list."""
        if not self.sources_used:
            return []
        return [s.strip() for s in self.sources_used.split(",") if s.strip()]

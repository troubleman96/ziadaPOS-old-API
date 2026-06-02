"""
apps/ai/admin.py

Django Admin for the Ziada AI app.
Provides a read-only audit log of AI conversations and messages.
Useful for debugging, monitoring credit usage, and reviewing AI responses.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    """Show messages inline within a conversation detail view."""
    model      = Message
    extra      = 0
    fields     = ["created_at", "role_display_inline", "content_preview", "model_used", "completion_tokens"]
    readonly_fields = ["created_at", "role_display_inline", "content_preview", "model_used", "completion_tokens"]
    can_delete = False
    ordering   = ["created_at"]

    def has_add_permission(self, request, obj=None):
        return False

    def role_display_inline(self, obj):
        color = "#6366f1" if obj.role == "user" else "#22c55e"
        return format_html('<span style="color:{};font-weight:600">{}</span>', color, obj.role.upper())
    role_display_inline.short_description = "Role"

    def content_preview(self, obj):
        return obj.content[:100] + ("…" if len(obj.content) > 100 else "")
    content_preview.short_description = "Content"


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """Admin view for AI conversations."""

    list_display = [
        "id_short", "user", "store",
        "title_display", "message_count_display",
        "is_active", "updated_at",
    ]
    list_display_links = ["id_short"]
    list_filter = ["store", "is_active", "updated_at"]
    search_fields = ["title", "user__username", "user__first_name"]
    list_select_related = ["user", "store", "organisation"]
    date_hierarchy = "created_at"
    ordering = ["-updated_at"]

    readonly_fields = [
        "id", "user", "store", "organisation",
        "title", "first_message_preview",
        "created_at", "updated_at",
    ]

    inlines = [MessageInline]

    def has_add_permission(self, request):
        return False

    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = "ID"

    def title_display(self, obj):
        return obj.title[:60] + ("…" if len(obj.title) > 60 else "")
    title_display.short_description = "Title"

    def message_count_display(self, obj):
        return obj.message_count
    message_count_display.short_description = "Messages"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Admin view for individual AI messages — read-only audit log."""

    list_display = [
        "id_short", "conversation",
        "role_display", "content_preview",
        "model_used", "tokens_display", "sources_used",
        "created_at",
    ]
    list_filter = ["role", "model_used"]
    search_fields = ["content", "conversation__title"]
    list_select_related = ["conversation", "conversation__user"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    readonly_fields = [
        "id", "conversation", "role", "content",
        "model_used", "prompt_tokens", "completion_tokens", "sources_used",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = "ID"

    def role_display(self, obj):
        colors = {"user": "#6366f1", "assistant": "#22c55e", "system": "#94a3b8"}
        color = colors.get(obj.role, "#64748b")
        return format_html('<span style="color:{};font-weight:600">{}</span>', color, obj.role.upper())
    role_display.short_description = "Role"

    def content_preview(self, obj):
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")
    content_preview.short_description = "Content"

    def tokens_display(self, obj):
        if obj.role == "assistant":
            return f"{obj.prompt_tokens} + {obj.completion_tokens}"
        return "—"
    tokens_display.short_description = "Tokens (p+c)"

"""
apps/ai/api/serializers.py

Serializers for the AI assistant app.

ConversationSerializer    — full read (detail with messages)
ConversationListSerializer — lightweight read (sidebar list)
MessageSerializer         — individual message (user or assistant)
ChatMessageSerializer     — input validator for sending a new message
"""

from rest_framework import serializers

from ..models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    """
    Read serialiser for a single AI message.
    Used to return the assistant's response after a chat request.
    """

    sources = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "role", "content",
            "model_used",
            "prompt_tokens", "completion_tokens",
            "sources",
            "created_at",
        ]

    def get_sources(self, obj):
        """Return sources as a list instead of a comma-separated string."""
        return obj.sources_list


class ConversationListSerializer(serializers.ModelSerializer):
    """
    Lightweight serialiser for the sidebar conversation list.
    Only shows what's needed for the history list in /ai sidebar.
    """

    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "title", "first_message_preview",
            "message_count", "is_active",
            "created_at", "updated_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    """
    Full read serialiser for a conversation — includes all messages.
    Used by GET /ai/conversations/{id}/
    """

    messages = MessageSerializer(many=True, read_only=True)
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "title", "first_message_preview",
            "message_count",
            "messages",
            "is_active",
            "created_at", "updated_at",
        ]


class ChatMessageSerializer(serializers.Serializer):
    """
    Input validator for POST /ai/conversations/{id}/chat/
    (or POST /ai/chat/ to start a new conversation + send first message)

    The frontend sends:
      { "message": "Nionyeshe uchambuzi wa mauzo wiki hii" }
    """

    message = serializers.CharField(
        max_length=4000,
        help_text="The user's message (Swahili or English).",
    )

    def validate_message(self, value):
        """Strip whitespace and reject empty messages."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value


class StartConversationSerializer(serializers.Serializer):
    """
    Input validator for POST /ai/chat/ (start conversation + send first message).
    Optionally accepts a title — if not provided, it's auto-generated.
    """

    message = serializers.CharField(
        max_length=4000,
        help_text="The first user message.",
    )
    title = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional conversation title (auto-generated if empty).",
    )

    def validate_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value

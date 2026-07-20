"""
apps/ai/api/views.py

API views for the Ziada AI assistant.

Referenced UI page: /ai
  - Left sidebar: conversation history list
  - Main panel: message thread
  - Input bar: send a message
  - Context chip: shows which data sources are loaded

Endpoints:
  GET  /api/v1/ai/conversations/          → list all conversations for this user
  POST /api/v1/ai/chat/                   → start a NEW conversation + get first reply
  GET  /api/v1/ai/conversations/{id}/     → get full conversation with all messages
  POST /api/v1/ai/conversations/{id}/chat/ → continue an EXISTING conversation
  PATCH /api/v1/ai/conversations/{id}/    → rename or archive a conversation
  GET  /api/v1/ai/suggestions/            → get contextual suggested prompts
  GET  /api/v1/ai/usage/                  → real usage log (tokens/model/date) + credit status

Flow:
  1. Frontend sends POST /ai/chat/ with the first message
  2. Backend creates a Conversation + saves user Message
  3. Builds store context system prompt
  4. Calls OpenRouter, saves assistant Message
  5. Returns { conversation_id, message } so frontend can redirect to /ai?c={id}
  6. Subsequent messages go to POST /ai/conversations/{id}/chat/
"""

import logging

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.accounts.models import AICredit
from apps.core.response import created_response, error_response, success_response

from ..models import Conversation, Message
from ..service import build_store_context, chat
from .serializers import (
    ChatMessageSerializer,
    ConversationListSerializer,
    ConversationSerializer,
    MessageSerializer,
    StartConversationSerializer,
)

logger = logging.getLogger(__name__)


class ConversationListView(APIView):
    """
    GET /api/v1/ai/conversations/

    Returns all active conversations for the authenticated user,
    ordered by most recent activity.
    Used to populate the sidebar history list on the /ai page.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return list of conversations."""
        conversations = Conversation.objects.filter(
            user=request.user,
            store=request.user.store,
            is_active=True,
        )
        serializer = ConversationListSerializer(conversations, many=True)
        return success_response(
            data=serializer.data,
            message="Conversations.",
        )


class StartChatView(APIView):
    """
    POST /api/v1/ai/chat/

    Start a new AI conversation and get the first assistant reply.

    Input:  { "message": "Habari, nionyeshe mauzo ya leo" }
    Output: { "conversation_id": "...", "message": { ...assistant message } }

    Creates a new Conversation, saves the user message, calls OpenRouter,
    saves and returns the assistant message.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Start a new conversation."""
        serializer = StartConversationSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data
        user_message = data["message"]

        # Ensure the user's organisation has AI credits
        user = request.user
        store = user.store
        if not store:
            return error_response("User must belong to a store to use AI.", status=400)

        organisation = store.organisation

        # Create conversation
        conversation = Conversation.objects.create(
            user=user,
            store=store,
            organisation=organisation,
            title=data.get("title") or user_message[:60],
        )

        try:
            # Process the chat turn (save user msg → call AI → save response)
            assistant_message = chat(conversation, user_message)
        except Exception as exc:
            logger.exception("Chat failed: %s", exc)
            return error_response("AI chat failed. Please try again.", status=500)

        return created_response(
            data={
                "conversation_id": str(conversation.id),
                "message":         MessageSerializer(assistant_message).data,
            },
            message="AI response.",
        )


class ConversationDetailView(APIView):
    """
    GET  /api/v1/ai/conversations/{id}/  → full conversation with messages
    PATCH /api/v1/ai/conversations/{id}/ → rename or archive
    """

    permission_classes = [IsAuthenticated]

    def _get_conversation(self, conversation_id, user):
        """Get a conversation scoped to the user."""
        try:
            return Conversation.objects.get(
                id=conversation_id,
                user=user,
            )
        except Conversation.DoesNotExist:
            return None

    def get(self, request, conversation_id):
        """GET — return full conversation with all messages."""
        conversation = self._get_conversation(conversation_id, request.user)
        if not conversation:
            return error_response("Conversation not found.", status=404)

        return success_response(
            data=ConversationSerializer(conversation).data,
            message="Conversation.",
        )

    def patch(self, request, conversation_id):
        """PATCH — rename or archive a conversation."""
        conversation = self._get_conversation(conversation_id, request.user)
        if not conversation:
            return error_response("Conversation not found.", status=404)

        # Allow renaming
        if "title" in request.data:
            title = str(request.data["title"]).strip()[:200]
            if title:
                conversation.title = title

        # Allow archiving
        if "is_active" in request.data:
            conversation.is_active = bool(request.data["is_active"])

        conversation.save(update_fields=["title", "is_active", "updated_at"])
        return success_response(
            data=ConversationListSerializer(conversation).data,
            message="Conversation updated.",
        )


class ContinueChatView(APIView):
    """
    POST /api/v1/ai/conversations/{id}/chat/

    Continue an existing conversation with a new message.

    Input:  { "message": "Niambie zaidi kuhusu Sukari" }
    Output: { "message": { ...assistant message } }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        """Send a new message in an existing conversation."""
        try:
            conversation = Conversation.objects.get(
                id=conversation_id,
                user=request.user,
            )
        except Conversation.DoesNotExist:
            return error_response("Conversation not found.", status=404)

        serializer = ChatMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        user_message = serializer.validated_data["message"]

        try:
            assistant_message = chat(conversation, user_message)
        except Exception as exc:
            logger.exception("Chat failed: %s", exc)
            return error_response("AI chat failed. Please try again.", status=500)

        return created_response(
            data={"message": MessageSerializer(assistant_message).data},
            message="AI response.",
        )


class AISuggestionsView(APIView):
    """
    GET /api/v1/ai/suggestions/

    Returns contextual suggested prompts based on the store's current state.
    These are shown as clickable chips in the /ai page.

    The suggestions are dynamic — if there are overdue credits, suggest a credit
    follow-up. If there are low stock items, suggest a reorder review.
    Always include some static standard prompts as well.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return contextual prompt suggestions."""
        store = request.user.store
        ctx = build_store_context(store)

        suggestions = []

        # Dynamic: low stock
        if ctx.get("low_stock_items"):
            count = len(ctx["low_stock_items"])
            suggestions.append({
                "icon":  "📦",
                "label": f"Bidhaa {count} zinahitaji kununuliwa — nionyeshe" if count > 1
                          else "Kuna bidhaa 1 inayohitaji kununuliwa — nionyeshe",
                "key":   "stock",
            })

        # Dynamic: overdue credits
        credit_customers = ctx.get("customers_with_credit", [])
        if credit_customers:
            suggestions.append({
                "icon":  "💳",
                "label": f"Hali ya madeni — wateja {len(credit_customers)} wana deni",
                "key":   "credit",
            })

        # Always include these
        suggestions += [
            {"icon": "📊", "label": "Nionyeshe uchambuzi wa mauzo wiki hii",   "key": "sales"},
            {"icon": "💰", "label": "Uchambuzi wa faida na margin mwezi huu",  "key": "profit"},
            {"icon": "📈", "label": "Toa ripoti fupi ya leo kwa WhatsApp",     "key": "default"},
            {"icon": "🔮", "label": "Tabiri mauzo ya wiki ijayo",              "key": "default"},
        ]

        # Return AI credit info so the frontend can show the credit meter
        ai_credit = AICredit.get_or_create_current(store.organisation)

        return success_response(
            data={
                "suggestions":     suggestions[:6],
                "ai_credits": {
                    "remaining":  ai_credit.remaining,
                    "used":       ai_credit.used,
                    "allocated":  ai_credit.allocated,
                    "pct_used":   ai_credit.percentage_used,
                },
            },
            message="AI suggestions.",
        )


class AIUsageView(APIView):
    """
    GET /api/v1/ai/usage/

    Real usage log for the store's AI assistant — how it's actually being
    used, not a mock. Backs the "View usage" link on the AI credits card.

    Returns:
      - totals: message/token counts across the store's whole history
      - this_month: same, scoped to the current AICredit period
      - recent: the last 50 assistant replies (model, tokens, conversation, date)
      - ai_credits: same shape as /ai/suggestions/, for the header
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count

        from ..models import Message

        store = request.user.store
        if not store:
            return error_response("User must belong to a store to use AI.", status=400)

        organisation = store.organisation
        assistant_messages = Message.objects.filter(
            conversation__store=store,
            role=Message.ROLE_ASSISTANT,
        ).select_related("conversation")

        agg = assistant_messages.aggregate(
            message_count=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
        )

        now = timezone.now()
        this_month = assistant_messages.filter(
            created_at__year=now.year, created_at__month=now.month,
        )
        month_agg = this_month.aggregate(
            message_count=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
        )

        recent = assistant_messages.order_by("-created_at")[:50]

        ai_credit = AICredit.get_or_create_current(organisation)

        return success_response(
            data={
                "totals": {
                    "messages":          agg["message_count"] or 0,
                    "prompt_tokens":     agg["prompt_tokens"] or 0,
                    "completion_tokens": agg["completion_tokens"] or 0,
                },
                "this_month": {
                    "messages":          month_agg["message_count"] or 0,
                    "prompt_tokens":     month_agg["prompt_tokens"] or 0,
                    "completion_tokens": month_agg["completion_tokens"] or 0,
                },
                "recent": [
                    {
                        "id":                 str(m.id),
                        "conversation_title": m.conversation.title,
                        "model_used":         m.model_used,
                        "prompt_tokens":      m.prompt_tokens,
                        "completion_tokens":  m.completion_tokens,
                        "created_at":         m.created_at,
                    }
                    for m in recent
                ],
                "ai_credits": {
                    "remaining":  ai_credit.remaining,
                    "used":       ai_credit.used,
                    "allocated":  ai_credit.allocated,
                    "pct_used":   ai_credit.percentage_used,
                },
                "ngamia_configured": organisation.ngamia_configured,
            },
            message="AI usage.",
        )

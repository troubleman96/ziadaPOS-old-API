"""
apps/ai/api/urls.py

Ziada AI routes. Mounted at: /api/v1/ai/

  GET  /conversations/          → list all conversations (sidebar history)
  POST /chat/                   → start a new conversation + get first reply
  GET  /conversations/{id}/     → get full conversation with all messages
  PATCH /conversations/{id}/    → rename or archive a conversation
  POST /conversations/{id}/chat/ → continue an existing conversation
  GET  /suggestions/            → contextual prompt suggestions + credit status
  GET  /usage/                  → real usage log + credit status
"""

from django.urls import path

from .views import (
    AISuggestionsView,
    AIUsageView,
    ContinueChatView,
    ConversationDetailView,
    ConversationListView,
    StartChatView,
)

urlpatterns = [
    # Conversation management
    path("conversations/",      ConversationListView.as_view(),   name="ai-conversations"),
    path("conversations/<uuid:conversation_id>/",
         ConversationDetailView.as_view(), name="ai-conversation-detail"),

    # Chat turns
    path("chat/",               StartChatView.as_view(),          name="ai-chat-start"),
    path("conversations/<uuid:conversation_id>/chat/",
         ContinueChatView.as_view(), name="ai-chat-continue"),

    # Contextual suggestions + credit status
    path("suggestions/",        AISuggestionsView.as_view(),      name="ai-suggestions"),
    path("usage/",               AIUsageView.as_view(),           name="ai-usage"),
]

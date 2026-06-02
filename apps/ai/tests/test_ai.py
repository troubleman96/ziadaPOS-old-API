"""
apps/ai/tests/test_ai.py

Tests for the Ziada AI app: conversation creation, chat continuation,
credit deduction, context building, and suggestion endpoints.

Note: Actual OpenRouter API calls are mocked so tests run without
an internet connection or API key.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import AICredit, Organisation, Store, User
from apps.ai.models import Conversation, Message


def make_base_fixtures():
    """Create org, store, and cashier user."""
    org     = Organisation.objects.create(name="Test Org")
    store   = Store.objects.create(organisation=org, name="Main Store", area="Kariakoo")
    cashier = User.objects.create_user(
        username="cashier1", password="pass123!", role="cashier", store=store
    )
    return org, store, cashier


def auth(client, username, password="pass123!"):
    """Authenticate an APIClient."""
    resp = client.post(reverse("token_obtain_pair"), {"username": username, "password": password})
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


# Mock response that call_openrouter will return in tests
MOCK_AI_RESPONSE = {
    "success":           True,
    "content":           "Habari! Leo duka lako limepata mapato mazuri.",
    "model":             "openai/gpt-4o-mini",
    "prompt_tokens":     150,
    "completion_tokens": 80,
}


class ConversationModelTests(TestCase):
    """Unit tests for the Conversation model."""

    def setUp(self):
        self.org, self.store, self.cashier = make_base_fixtures()

    def test_conversation_creation(self):
        """Can create a Conversation with required fields."""
        conv = Conversation.objects.create(
            user=self.cashier,
            store=self.store,
            organisation=self.org,
            title="Test conversation",
        )
        self.assertEqual(conv.title, "Test conversation")
        self.assertTrue(conv.is_active)

    def test_message_count_property(self):
        """message_count returns the correct count."""
        conv = Conversation.objects.create(
            user=self.cashier, store=self.store, organisation=self.org
        )
        self.assertEqual(conv.message_count, 0)

        Message.objects.create(
            conversation=conv, role=Message.ROLE_USER, content="Hello"
        )
        self.assertEqual(conv.message_count, 1)

    def test_message_sources_list_property(self):
        """sources_list parses comma-separated sources correctly."""
        conv = Conversation.objects.create(
            user=self.cashier, store=self.store, organisation=self.org
        )
        msg = Message.objects.create(
            conversation=conv,
            role=Message.ROLE_ASSISTANT,
            content="Response",
            sources_used="Sales data,Inventory,Credits",
        )
        self.assertEqual(msg.sources_list, ["Sales data", "Inventory", "Credits"])

    def test_empty_sources_returns_empty_list(self):
        """Empty sources_used returns empty list."""
        conv = Conversation.objects.create(
            user=self.cashier, store=self.store, organisation=self.org
        )
        msg = Message.objects.create(
            conversation=conv, role=Message.ROLE_USER, content="Hi"
        )
        self.assertEqual(msg.sources_list, [])


class StartChatTests(TestCase):
    """Test POST /ai/chat/ — start a new conversation."""

    def setUp(self):
        self.client = APIClient()
        self.org, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Ensure the organisation has AI credits
        AICredit.objects.create(
            organisation=self.org,
            year=2026, month=5,
            used=0, allocated=100,
        )

    @patch("apps.ai.service.call_openrouter", return_value=MOCK_AI_RESPONSE)
    def test_starts_conversation_and_returns_reply(self, mock_call):
        """POST /ai/chat/ creates a conversation and returns the AI reply."""
        resp = self.client.post(
            reverse("ai-chat-start"),
            {"message": "Habari, nionyeshe mauzo ya leo"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data["data"]
        self.assertIn("conversation_id", data)
        self.assertIn("message", data)
        self.assertEqual(data["message"]["role"], "assistant")

    @patch("apps.ai.service.call_openrouter", return_value=MOCK_AI_RESPONSE)
    def test_conversation_saved_to_db(self, mock_call):
        """Starting a chat creates a Conversation + 2 Messages (user + assistant)."""
        self.client.post(
            reverse("ai-chat-start"),
            {"message": "Nionyeshe uchambuzi wa mauzo"},
            format="json",
        )
        self.assertEqual(Conversation.objects.filter(user=self.cashier).count(), 1)
        conv = Conversation.objects.get(user=self.cashier)
        self.assertEqual(conv.messages.count(), 2)  # user + assistant

    @patch("apps.ai.service.call_openrouter", return_value=MOCK_AI_RESPONSE)
    def test_ai_credit_deducted(self, mock_call):
        """Each chat reply deducts 1 AI credit."""
        credit = AICredit.objects.get(organisation=self.org)
        before = credit.used

        self.client.post(
            reverse("ai-chat-start"),
            {"message": "Test message"},
            format="json",
        )
        credit.refresh_from_db()
        self.assertEqual(credit.used, before + 1)

    def test_empty_message_rejected(self):
        """Empty message is rejected."""
        resp = self.client.post(
            reverse("ai-chat-start"),
            {"message": "   "},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_denied(self):
        """Unauthenticated request is rejected."""
        client = APIClient()
        resp = client.post(reverse("ai-chat-start"), {"message": "Hi"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class ContinueChatTests(TestCase):
    """Test POST /ai/conversations/{id}/chat/ — continue a conversation."""

    def setUp(self):
        self.client = APIClient()
        self.org, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        AICredit.objects.create(
            organisation=self.org, year=2026, month=5, used=0, allocated=100
        )
        # Create a conversation
        self.conv = Conversation.objects.create(
            user=self.cashier,
            store=self.store,
            organisation=self.org,
            title="Test chat",
        )

    @patch("apps.ai.service.call_openrouter", return_value=MOCK_AI_RESPONSE)
    def test_continue_adds_messages(self, mock_call):
        """Continuing a conversation adds user + assistant messages."""
        resp = self.client.post(
            reverse("ai-chat-continue", args=[self.conv.id]),
            {"message": "Niambie zaidi"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.conv.refresh_from_db()
        # 2 messages: user + assistant
        self.assertEqual(self.conv.messages.count(), 2)

    def test_nonexistent_conversation_returns_404(self):
        """Sending to a non-existent conversation returns 404."""
        import uuid
        resp = self.client.post(
            reverse("ai-chat-continue", args=[uuid.uuid4()]),
            {"message": "Hello"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class ConversationListTests(TestCase):
    """Test GET /ai/conversations/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.org, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Create some conversations
        Conversation.objects.create(
            user=self.cashier, store=self.store, organisation=self.org,
            title="Sales analysis"
        )
        Conversation.objects.create(
            user=self.cashier, store=self.store, organisation=self.org,
            title="Stock check"
        )

    def test_list_returns_user_conversations(self):
        """GET /ai/conversations/ returns conversations for this user."""
        resp = self.client.get(reverse("ai-conversations"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["data"]), 2)

    def test_only_own_conversations_returned(self):
        """User cannot see other users' conversations."""
        other_org   = Organisation.objects.create(name="Other Org")
        other_store = Store.objects.create(organisation=other_org, name="Other", area="Dar")
        other_user  = User.objects.create_user(
            username="other", password="pass123!", role="cashier", store=other_store
        )
        Conversation.objects.create(
            user=other_user, store=other_store, organisation=other_org,
            title="Other user's chat"
        )
        resp = self.client.get(reverse("ai-conversations"))
        titles = [c["title"] for c in resp.data["data"]]
        self.assertNotIn("Other user's chat", titles)


class AISuggestionsTests(TestCase):
    """Test GET /ai/suggestions/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.org, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")
        AICredit.objects.create(
            organisation=self.org, year=2026, month=5, used=10, allocated=100
        )

    def test_suggestions_returned(self):
        """GET /ai/suggestions/ returns a list of suggestions."""
        resp = self.client.get(reverse("ai-suggestions"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIn("suggestions", data)
        self.assertIn("ai_credits", data)
        self.assertIsInstance(data["suggestions"], list)

    def test_credit_info_in_response(self):
        """Suggestions response includes remaining AI credits."""
        resp = self.client.get(reverse("ai-suggestions"))
        credits = resp.data["data"]["ai_credits"]
        self.assertEqual(credits["remaining"], 90)  # 100 - 10
        self.assertEqual(credits["used"], 10)


class ZeroCreditTest(TestCase):
    """Test that AI returns a friendly message when credits are exhausted."""

    def setUp(self):
        self.client = APIClient()
        self.org, self.store, self.cashier = make_base_fixtures()
        auth(self.client, "cashier1")

        # Exhaust all AI credits
        AICredit.objects.create(
            organisation=self.org, year=2026, month=5,
            used=100, allocated=100,
        )

    def test_returns_fallback_when_no_credits(self):
        """When AI credits are 0, returns a friendly 'credits exhausted' message."""
        resp = self.client.post(
            reverse("ai-chat-start"),
            {"message": "Habari"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        content = resp.data["data"]["message"]["content"]
        # Should contain the credits exhausted message (in Swahili or English)
        self.assertTrue(
            "credits" in content.lower() or "credit" in content.lower()
        )

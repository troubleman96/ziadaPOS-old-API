"""
apps/ai/apps.py

AppConfig for the Ziada AI app.

Powers the /ai page — a Swahili/English bilingual business assistant
that has access to the store's live data (sales, inventory, credits).

LLM: OpenRouter API using openai/gpt-4o-mini for the MVP.
Context: Built from live DB data — recent transactions, low-stock items,
         outstanding credits, top products — injected into the system prompt.

Credit tracking: Each AI response costs 1 credit (tracked via AICredit model
in the accounts app). If an organisation runs out of credits, the AI returns
a friendly upgrade message.
"""

from django.apps import AppConfig


class AIConfig(AppConfig):
    """Configuration for the Ziada AI assistant app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai_app"   # Avoid collision with Python 'ai' namespace
    verbose_name = "Ziada AI"

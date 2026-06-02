"""
apps/notebook/models.py

Internal notebook for store staff — memos, ideas, supplier notes, schedules.

Model:
  Note — a single notebook entry scoped to a store.

Design notes:
  - tags is a JSONField (list of strings) matching the UI's tag array.
  - All monetary tracking is NOT here; this is free-form text storage.
  - Notes are store-scoped (not per-user) so the whole team shares the notebook.
  - created_by tracks who wrote the note for display; deleting a user nullifies it
    but keeps the note intact.
"""

from django.conf import settings
from django.db import models

from apps.accounts.models import Organisation, Store
from apps.core.models import BaseModel


class Note(BaseModel):
    """
    A single notebook entry visible to all staff at a store.

    Maps directly to the UI's Note type:
      { id, title, content, date (derived from created_at), tags[] }
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="notes",
        help_text="Store this note belongs to.",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="notes",
        help_text="Organisation (for multi-store queries).",
    )

    # ── Content ────────────────────────────────────────────────────────────────
    title = models.CharField(
        max_length=300,
        help_text="Short note title shown in the note card header.",
    )
    content = models.TextField(
        blank=True,
        help_text="Full note body — shown in the edit modal and previewed (2 lines) on the card.",
    )

    # Tags stored as a JSON array of strings, e.g. ["Suppliers", "Ideas"]
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Tag list, e.g. ["Suppliers", "Ideas"]. Used for folder filtering in the UI.',
    )

    # ── Authorship ─────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
        help_text="Staff member who created the note.",
    )

    def __str__(self):
        return f"{self.store.name} | {self.title[:60]}"

    @property
    def date_label(self):
        """
        Human-readable relative date label matching the UI's display:
          'Just now' | 'Today' | 'Yesterday' | '2d ago' | '1w ago' | 'DD Mon'
        """
        from django.utils import timezone
        now  = timezone.now()
        diff = now - self.created_at
        mins  = int(diff.total_seconds() / 60)
        hours = int(diff.total_seconds() / 3600)
        days  = diff.days

        if mins < 2:
            return "Just now"
        if hours < 24 and days == 0:
            return "Today"
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days}d ago"
        if days < 14:
            return "1w ago"
        return self.created_at.strftime("%-d %b")

    class Meta:
        verbose_name = "Note"
        verbose_name_plural = "Notes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "-created_at"]),
        ]

"""
apps/core/models.py

Abstract base model that every Ziada model inherits from.

Why use an abstract base model?
  - Guarantees every table has `id` (UUID), `created_at`, and `updated_at`
  - UUIDs prevent sequential enumeration attacks on the API (vs integer PKs)
  - `updated_at` auto-updates on every save — great for cache invalidation
  - Abstract means no DB table is created for this class itself
"""

import uuid

from django.db import models


class BaseModel(models.Model):
    """
    Abstract base model for all Ziada database tables.

    Fields:
        id         — UUID primary key (non-sequential, safe to expose in API)
        created_at — timestamp of record creation (auto-set, never changes)
        updated_at — timestamp of last update (auto-updates on every save)
    """

    # UUID primary key — more secure than sequential integers for public APIs
    # UUID4 is random — no sequential guessing of record IDs
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this record (UUID4).",
    )

    # Creation timestamp — set once when the record is first saved
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this record was created (UTC).",
    )

    # Update timestamp — automatically refreshed on every model.save() call
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when this record was last updated (UTC).",
    )

    class Meta:
        # Abstract = no DB table for BaseModel itself
        # All subclasses get the fields above as real columns
        abstract = True

        # Order by newest first by default (most list views want this)
        ordering = ["-created_at"]

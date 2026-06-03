"""
apps/reviews/models.py

StoreReview — a rating + short text submitted by a store owner/staff.
Used to power the "What our customers say" section on the landing page.

Trigger schedule (enforced frontend-side via localStorage):
  - 3  days after subscription created  → first ask
  - 12 days after subscription created  → second ask
  - 14 days after subscription created  → final ask
"""

from django.conf import settings
from django.db import models

from apps.accounts.models import Organisation, Store
from apps.core.models import BaseModel


class StoreReview(BaseModel):
    """
    A product review submitted by a Ziada POS user.

    Reviews are linked to the Organisation (not store) so that multi-store
    owners appear once on the landing page.

    Public reviews (is_public=True) are served without authentication so
    the marketing landing page can display them without a user session.
    """

    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    # Linked to the organisation (owner entity)
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="reviews",
        help_text="Organisation that submitted this review.",
    )

    # The user who submitted
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        help_text="User who submitted the review.",
    )

    # 1–5 star rating
    rating = models.PositiveSmallIntegerField(
        choices=RATING_CHOICES,
        help_text="Rating from 1 (poor) to 5 (excellent).",
    )

    # Optional title e.g. "Great POS for my duka"
    title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Short headline for the review.",
    )

    # Main review body
    body = models.TextField(
        blank=True,
        default="",
        help_text="Full review text.",
    )

    # Business type for context on the landing page (e.g. "Retail Shop")
    business_type_display = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Human-readable business type, copied from org on creation.",
    )

    # City/region for social proof (e.g. "Dar es Salaam")
    region_display = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Region, copied from org on creation.",
    )

    # Which trigger prompt generated this review (3d / 12d / 14d / manual)
    trigger = models.CharField(
        max_length=20,
        blank=True,
        default="manual",
        help_text="Which trigger generated this review prompt.",
    )

    # Moderation — admin marks public before it appears on landing page
    is_public = models.BooleanField(
        default=False,
        help_text="Only public reviews appear on the landing page.",
    )

    class Meta:
        verbose_name = "Store Review"
        verbose_name_plural = "Store Reviews"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.organisation.name} — {self.rating}★ ({self.created_at.date()})"

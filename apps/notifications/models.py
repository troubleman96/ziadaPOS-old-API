"""
apps/notifications/models.py

EmailVerificationToken — one-use token for email address confirmation.
Generated on registration, invalidated after first use or 72 hours.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailVerificationToken(models.Model):
    user    = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_token",
    )
    token      = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Email Verification Token"

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(hours=72)

    def __str__(self):
        return f"Token for {self.user.email or self.user.username}"

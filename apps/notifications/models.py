"""
apps/notifications/models.py

EmailVerificationToken — one-use link token for email address confirmation.
Generated on registration, invalidated after first use or 72 hours.

PhoneOTP — one-use 6-digit code for phone number confirmation, sent via
SendAfrica SMS (the platform's own account, not a customer-facing org key).
Independent of email verification — a user can verify either, both, or
neither; is_email_verified and is_phone_verified are separate flags on User.
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


class PhoneOTP(models.Model):
    """
    A 6-digit SMS code issued to verify User.phone.

    Multiple rows can exist per user (one per request); only the newest
    unconsumed, unexpired one is valid. Expires after 5 minutes, allows
    5 wrong attempts before the caller must request a fresh code.
    """

    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="phone_otps",
    )
    phone      = models.CharField(max_length=10, help_text="Phone number this code was sent to.")
    code       = models.CharField(max_length=6)
    attempts   = models.PositiveSmallIntegerField(default=0)
    consumed   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phone OTP"
        ordering = ["-created_at"]

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)

    def __str__(self):
        return f"OTP for {self.phone} ({'used' if self.consumed else 'pending'})"

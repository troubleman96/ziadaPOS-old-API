"""
apps/notifications/sms.py

Central SMS dispatch module — sends via the SendAfrica API
(https://docs.sendafrica.online).

Each Organisation pastes its own API key in Settings → Integrations
(Organisation.sendafrica_api_key). There is no platform-wide fallback key —
SMS is disabled for an organisation until they configure one.

Functions:
  send_sms(organisation, to, message, sender_id=None) — send one SMS
  check_balance(organisation)                          — remaining SMS credits
"""

import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = getattr(settings, "SENDAFRICA_BASE_URL", "https://api.sendafrica.online")
TIMEOUT = 10.0


class SmsError(Exception):
    """Raised when an SMS could not be sent. `.code` mirrors SendAfrica's error code."""

    def __init__(self, message, code="error"):
        super().__init__(message)
        self.code = code


# Valid Tanzania mobile prefixes per SendAfrica's phone format rules.
_TZ_PREFIXES = ("071", "072", "073", "074", "075", "076", "077", "078")


def normalize_tz_phone(raw: str) -> str:
    """
    Normalise a Tanzania phone number to local '0712345678' form accepted by
    SendAfrica (which also accepts '+255712345678' / '255712345678', but the
    local form matches what's stored on Customer/User records here).
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("255") and len(digits) == 12:
        digits = "0" + digits[3:]
    if len(digits) == 9 and not digits.startswith("0"):
        digits = "0" + digits
    return digits


def send_sms(organisation, to: str, message: str, sender_id: str | None = None) -> dict:
    """
    Send an SMS via SendAfrica on behalf of `organisation`.

    Returns {"message_id": str, "status": str, "credits_used": int} on success.
    Raises SmsError on failure (missing key, invalid phone, insufficient credits, etc).
    """
    if not organisation or not organisation.sendafrica_api_key:
        raise SmsError(
            "SMS is not configured for this organisation. Add a SendAfrica API key in Settings → Integrations.",
            code="not_configured",
        )

    phone = normalize_tz_phone(to)
    if not phone.startswith(_TZ_PREFIXES) or len(phone) != 10:
        raise SmsError(f"'{to}' is not a valid Tanzania mobile number.", code="invalid_phone")

    payload = {"to": phone, "message": message}
    from_id = sender_id or organisation.sms_sender_id
    if from_id:
        payload["from"] = from_id

    try:
        resp = httpx.post(
            f"{BASE_URL}/v1/sms/",
            headers={
                "X-API-Key": organisation.sendafrica_api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.error("SendAfrica request failed for org %s: %s", organisation.id, exc)
        raise SmsError("Could not reach the SMS provider. Please try again.", code="network_error") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise SmsError("SMS provider returned an invalid response.", code="server_error") from exc

    if not data.get("success"):
        err = data.get("error") or {}
        code = err.get("code", "error")
        msg = err.get("message", "SMS send failed.")
        logger.warning("SendAfrica error for org %s: [%s] %s", organisation.id, code, msg)
        raise SmsError(msg, code=code)

    result = data["data"]
    logger.info(
        "SMS sent for org %s to %s (message_id=%s, credits_used=%s)",
        organisation.id, phone, result.get("message_id"), result.get("credits_used"),
    )
    return {
        "message_id": result.get("message_id"),
        "status": result.get("status"),
        "credits_used": result.get("credits_used"),
    }


def check_balance(organisation) -> dict:
    """
    Return {"balance": int} of remaining SMS credits for `organisation`.
    Raises SmsError if no key is configured or the request fails.
    """
    if not organisation or not organisation.sendafrica_api_key:
        raise SmsError("SMS is not configured for this organisation.", code="not_configured")

    try:
        resp = httpx.get(
            f"{BASE_URL}/v1/credits/balance",
            headers={"X-API-Key": organisation.sendafrica_api_key},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise SmsError("Could not reach the SMS provider. Please try again.", code="network_error") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise SmsError("SMS provider returned an invalid response.", code="server_error") from exc

    if not data.get("success"):
        err = data.get("error") or {}
        raise SmsError(err.get("message", "Could not check SMS balance."), code=err.get("code", "error"))

    return {"balance": data["data"].get("balance", 0)}

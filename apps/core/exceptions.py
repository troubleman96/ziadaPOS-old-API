"""
apps/core/exceptions.py

Custom exception handler for Django REST Framework.

Converts all DRF exceptions (validation errors, permission denied, not found,
etc.) into our standard error envelope so the frontend always receives a
consistent response shape.

Registered in settings.py:
    REST_FRAMEWORK = {
        "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
    }
"""

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom DRF exception handler.

    Processing order:
    1. Call DRF's default handler first (handles most exceptions)
    2. If DRF handled it, reformat to our standard envelope
    3. If DRF didn't handle it (unexpected exception), return a generic 500

    Args:
        exc     : The raised exception.
        context : DRF context dict (view, request, args, kwargs).

    Returns:
        Response with standard error envelope, or None if unhandled.
    """
    # Step 1: Let DRF handle the exception first
    response = drf_exception_handler(exc, context)

    if response is not None:
        # Step 2: DRF handled it — reformat to our envelope
        # DRF puts errors in response.data which may be a dict or list

        # Determine a human-readable message from the status code
        message = _status_to_message(response.status_code, response.data)

        # Extract field-level errors (DRF validation errors are dicts)
        errors = response.data if isinstance(response.data, dict) else {"detail": response.data}

        # Replace DRF's default response body with our envelope
        response.data = {
            "success": False,
            "message": message,
            "data": None,
            "errors": errors,
        }

        return response

    # Step 3: Unhandled exception (server error)
    # Log it so we know something went wrong, then return a generic 500
    logger.exception("Unhandled exception in view: %s", str(exc))
    return Response(
        {
            "success": False,
            "message": "An unexpected server error occurred.",
            "data": None,
            "errors": {"detail": "Internal server error."},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _status_to_message(status_code: int, data) -> str:
    """
    Map HTTP status codes to human-readable messages.
    Falls back to the DRF 'detail' field if available.
    """
    # Check if DRF included a 'detail' message we can use directly
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])

    # Otherwise use a generic message by status code
    messages = {
        400: "Bad request — please check your input.",
        401: "Authentication required. Please log in.",
        403: "You do not have permission to perform this action.",
        404: "The requested resource was not found.",
        405: "Method not allowed.",
        409: "Conflict — this resource already exists or is in use.",
        422: "Validation failed — please check the errors.",
        429: "Too many requests — please slow down.",
        500: "Internal server error.",
        503: "Service temporarily unavailable.",
    }
    return messages.get(status_code, f"HTTP {status_code}")

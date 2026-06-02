"""
apps/core/response.py

Standard API response format for all Ziada endpoints.

Every response — success or error — uses the same envelope so the frontend
knows exactly what shape to expect.

Standard response envelope:
{
    "success": true | false,       // did the request succeed?
    "message": "Human description", // optional human-readable message
    "data":    { ... } | [ ... ],  // the actual payload (null on errors)
    "errors":  { ... } | null,     // field-level or global errors (null on success)
    "meta":    {                   // pagination / request metadata (optional)
        "page": 1,
        "total": 100,
        "page_size": 50,
        ...
    }
}

Usage in views:
    from apps.core.response import success_response, error_response

    return success_response(data=serializer.data, message="Product created")
    return error_response(message="Not found", status=404)
"""

from rest_framework.response import Response


def success_response(
    data=None,
    message: str = "OK",
    meta: dict = None,
    status: int = 200,
) -> Response:
    """
    Build a successful API response.

    Args:
        data    : The primary payload — dict, list, or None.
        message : Human-readable success message.
        meta    : Optional dict with pagination / extra context.
        status  : HTTP status code (default 200).

    Returns:
        DRF Response with the standard envelope.

    Example:
        return success_response(
            data={"id": "...", "name": "Unga wa Sembe"},
            message="Product retrieved",
        )
    """
    body = {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
    }

    # Only include `meta` key if caller provided it (keeps responses lean)
    if meta is not None:
        body["meta"] = meta

    return Response(body, status=status)


def error_response(
    message: str = "An error occurred",
    errors=None,
    status: int = 400,
) -> Response:
    """
    Build an error API response.

    Args:
        message : Human-readable error description.
        errors  : Field-level errors dict or list (e.g. from serializer.errors).
        status  : HTTP status code (default 400).

    Returns:
        DRF Response with the standard error envelope.

    Example:
        return error_response(
            message="Validation failed",
            errors=serializer.errors,
            status=422,
        )
    """
    return Response(
        {
            "success": False,
            "message": message,
            "data": None,
            "errors": errors,
        },
        status=status,
    )


def created_response(data=None, message: str = "Created successfully") -> Response:
    """Shortcut for HTTP 201 Created responses."""
    return success_response(data=data, message=message, status=201)


def no_content_response(message: str = "Deleted successfully") -> Response:
    """Shortcut for HTTP 204 No Content responses."""
    return Response(
        {"success": True, "message": message, "data": None, "errors": None},
        status=204,
    )

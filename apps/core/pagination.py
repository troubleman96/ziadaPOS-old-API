"""
apps/core/pagination.py

Custom pagination class for Ziada API list endpoints.

All list endpoints automatically paginate using this class (configured in
settings.REST_FRAMEWORK).

The response wraps DRF's default pagination with our standard envelope so
the frontend always sees:
{
    "success": true,
    "message": "OK",
    "data": [ ... ],          // the current page items
    "errors": null,
    "meta": {
        "total_count": 150,   // total records across all pages
        "page_size":   50,    // items per page
        "current_page": 2,    // 1-based current page number
        "total_pages": 3,     // total number of pages
        "next":     "http://...?page=3",  // null if last page
        "previous": "http://...?page=1",  // null if first page
    }
}
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    """
    Default pagination for all Ziada list endpoints.

    Query params:
        ?page=2         → jump to page 2
        ?page_size=25   → override items per page (max 200)
    """

    # Default items per page (overridable via ?page_size=)
    page_size = 50

    # Allow the frontend to override page size per request
    page_size_query_param = "page_size"

    # Cap to prevent someone requesting 10,000 records at once
    max_page_size = 200

    # Use 1-based page numbering (?page=1, ?page=2, ...)
    page_query_param = "page"

    def get_paginated_response(self, data):
        """
        Override DRF's default response to use our standard envelope format.
        This ensures ALL list endpoints have the same response shape.
        """
        return Response(
            {
                "success": True,
                "message": "OK",
                "data": data,
                "errors": None,
                "meta": {
                    # Total record count across ALL pages
                    "total_count": self.page.paginator.count,
                    # Items per page (respects ?page_size override)
                    "page_size": self.get_page_size(self.request),
                    # Current page number (1-based)
                    "current_page": self.page.number,
                    # Total number of pages
                    "total_pages": self.page.paginator.num_pages,
                    # URL for the next page (null if on last page)
                    "next": self.get_next_link(),
                    # URL for the previous page (null if on first page)
                    "previous": self.get_previous_link(),
                },
            }
        )

    def get_paginated_response_schema(self, schema):
        """Provide OpenAPI schema hint for the paginated response."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "data": schema,
                "errors": {"type": "object", "nullable": True},
                "meta": {
                    "type": "object",
                    "properties": {
                        "total_count": {"type": "integer"},
                        "page_size":   {"type": "integer"},
                        "current_page": {"type": "integer"},
                        "total_pages": {"type": "integer"},
                        "next": {"type": "string", "nullable": True},
                        "previous": {"type": "string", "nullable": True},
                    },
                },
            },
        }

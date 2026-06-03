"""
apps/reviews/api/views.py

POST /api/v1/reviews/         → submit a review (authenticated owner/staff)
GET  /api/v1/reviews/public/  → list public reviews for landing page (AllowAny)
"""

import logging

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.response import created_response, error_response, success_response

from ..models import StoreReview
from .serializers import StoreReviewCreateSerializer, StoreReviewPublicSerializer

logger = logging.getLogger(__name__)


class SubmitReviewView(APIView):
    """POST /api/v1/reviews/ — submit a review for this organisation."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not hasattr(user, "organisation") or not user.organisation:
            return error_response("No organisation linked to this account.", status=400)

        org = user.organisation

        serializer = StoreReviewCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        from apps.accounts.models import Organisation
        review = serializer.save(
            organisation=org,
            reviewer=user,
            business_type_display=org.get_business_type_display() if hasattr(org, "get_business_type_display") else org.business_type,
            region_display=org.region or "",
        )
        logger.info("Review submitted by %s (org %s, rating %d)", user.username, org.name, review.rating)
        return created_response(
            data={"id": str(review.id), "rating": review.rating},
            message="Review submitted. Thank you!",
        )


class PublicReviewsView(APIView):
    """GET /api/v1/reviews/public/ — public reviews for the landing page."""

    permission_classes = [AllowAny]

    def get(self, request):
        qs = StoreReview.objects.filter(
            is_public=True,
            rating__gte=4,
        ).select_related("organisation", "reviewer").order_by("-created_at")[:20]

        serializer = StoreReviewPublicSerializer(qs, many=True)
        return success_response(
            data=serializer.data,
            message=f"{len(serializer.data)} public reviews.",
        )

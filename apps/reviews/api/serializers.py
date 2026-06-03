from rest_framework import serializers

from ..models import StoreReview


class StoreReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StoreReview
        fields = ["rating", "title", "body", "trigger"]

    def validate_rating(self, v):
        if not (1 <= v <= 5):
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return v


class StoreReviewPublicSerializer(serializers.ModelSerializer):
    org_name     = serializers.CharField(source="organisation.name", read_only=True)
    reviewer_name = serializers.SerializerMethodField()

    class Meta:
        model  = StoreReview
        fields = [
            "id", "rating", "title", "body",
            "org_name", "reviewer_name",
            "business_type_display", "region_display",
            "created_at",
        ]

    def get_reviewer_name(self, obj):
        if obj.reviewer:
            return obj.reviewer.get_full_name() or "Anonymous"
        return "Anonymous"

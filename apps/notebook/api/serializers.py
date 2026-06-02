"""
apps/notebook/api/serializers.py

Serializers for the notebook app.

NoteSerializer — full CRUD serializer.
  Reads: id, title, content, tags, date_label (computed), store, organisation,
         created_by, created_by_name, created_at, updated_at.
  Writes: title, content, tags.
  store and organisation are injected by the view, never from the request body.
"""

from rest_framework import serializers

from ..models import Note


class NoteSerializer(serializers.ModelSerializer):
    # Human-readable relative date label matching the UI ("Today", "2d ago", etc.)
    date_label = serializers.CharField(read_only=True)

    # Created-by display name — null-safe
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "id",
            "store",
            "organisation",
            "title",
            "content",
            "tags",
            "date_label",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "store",
            "organisation",
            "date_label",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None

    def validate_tags(self, value):
        """Ensure tags is a list of non-empty strings (max 10 tags, each ≤ 50 chars)."""
        if not isinstance(value, list):
            raise serializers.ValidationError("tags must be a list of strings.")
        cleaned = []
        for tag in value:
            if not isinstance(tag, str):
                raise serializers.ValidationError("Each tag must be a string.")
            tag = tag.strip()[:50]
            if tag:
                cleaned.append(tag)
        if len(cleaned) > 10:
            raise serializers.ValidationError("A note can have at most 10 tags.")
        return cleaned

"""
apps/notebook/api/views.py

Endpoints:
  GET    /api/v1/notebook/         → list notes for the current store
  POST   /api/v1/notebook/         → create a note
  GET    /api/v1/notebook/{id}/    → get one note
  PATCH  /api/v1/notebook/{id}/    → update title / content / tags
  DELETE /api/v1/notebook/{id}/    → delete note

Query params for list:
  ?tag=Suppliers        → filter by a single tag (case-insensitive contains)
  ?search=<term>        → full-text search on title + content
  ?ordering=-created_at (default) | created_at | title
"""

import logging

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.core.response import created_response, error_response, success_response

from ..models import Note
from .serializers import NoteSerializer

logger = logging.getLogger(__name__)


class NoteViewSet(ModelViewSet):
    """Full CRUD viewset for notebook notes, scoped to the requesting user's store."""

    serializer_class   = NoteSerializer
    permission_classes = [IsAuthenticated]
    http_method_names  = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Note.objects.filter(
            store=self.request.user.store
        ).select_related("created_by")

    # ── List ──────────────────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        tag    = request.query_params.get("tag")
        search = request.query_params.get("search")
        order  = request.query_params.get("ordering", "-created_at")

        if tag:
            # JSONField contains lookup — works on both PostgreSQL and SQLite
            queryset = queryset.filter(tags__icontains=tag)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(content__icontains=search)
            )

        # Safe ordering whitelist
        if order not in ("-created_at", "created_at", "title", "-title"):
            order = "-created_at"
        queryset = queryset.order_by(order)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):
        if not request.user.store:
            return error_response("User is not assigned to a store.", status=400)

        serializer = NoteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)

        note = serializer.save(
            store=request.user.store,
            organisation=request.user.store.organisation,
            created_by=request.user,
        )
        logger.info("User %s created note '%s'.", request.user.username, note.title)
        return created_response(
            data=NoteSerializer(note).data,
            message="Note created.",
        )

    # ── Retrieve ──────────────────────────────────────────────────────────────

    def retrieve(self, request, *args, **kwargs):
        note = self.get_object()
        return success_response(data=NoteSerializer(note).data)

    # ── Update ────────────────────────────────────────────────────────────────

    def partial_update(self, request, *args, **kwargs):
        note = self.get_object()
        serializer = NoteSerializer(note, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("Validation failed.", errors=serializer.errors)
        serializer.save()
        return success_response(
            data=NoteSerializer(note).data,
            message="Note updated.",
        )

    # ── Delete ────────────────────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        note = self.get_object()
        title = note.title
        note.delete()
        logger.info("User %s deleted note '%s'.", request.user.username, title)
        return success_response(message=f"Note '{title}' deleted.")

"""
apps/notebook/api/urls.py

Mounted at: /api/v1/notebook/

Router-generated endpoints:
  GET    /                 → list notes (?tag=, ?search=, ?ordering=)
  POST   /                 → create note
  GET    /{id}/            → note detail
  PATCH  /{id}/            → update note
  DELETE /{id}/            → delete note
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NoteViewSet

router = DefaultRouter()
router.register(r"", NoteViewSet, basename="note")

urlpatterns = [
    path("", include(router.urls)),
]

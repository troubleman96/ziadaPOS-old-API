"""
ASGI config for Ziada POS project.
Used by Daphne / Uvicorn for async support (WebSockets, etc.).
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ziada.settings.development")
application = get_asgi_application()

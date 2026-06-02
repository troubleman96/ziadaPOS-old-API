"""
WSGI config for Ziada POS project.
Used by Gunicorn / uWSGI in production.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ziada.settings.development")
application = get_wsgi_application()

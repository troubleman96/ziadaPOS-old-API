"""
Production settings for Ziada POS backend.

Key differences from development:
  - DEBUG = False
  - Strict ALLOWED_HOSTS and CORS
  - Secure cookie/HSTS settings
  - PostgreSQL required (no SQLite fallback)
  - File-based logging
"""

import dj_database_url
from decouple import config

from .base import *  # noqa: F401, F403

# ─────────────────────────────────────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────────────────────────────────────

DEBUG = False

# Gunicorn sits behind an Nginx reverse proxy that terminates TLS — trust its
# X-Forwarded-Proto header, otherwise Django thinks every request is plain
# HTTP and SECURE_SSL_REDIRECT below causes an infinite redirect loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Enforce HTTPS
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000          # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# ─────────────────────────────────────────────────────────────────────────────
# Database — PostgreSQL required in production
# ─────────────────────────────────────────────────────────────────────────────

DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL"),  # will raise if not set
        conn_max_age=600,
        ssl_require=True,
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# Logging — write to files in production
# ─────────────────────────────────────────────────────────────────────────────

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "ziada.log",  # noqa: F405
            "formatter": "verbose",
        },
        "error_file": {
            "level": "ERROR",
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "ziada_errors.log",  # noqa: F405
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["file", "error_file"],
        "level": "INFO",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# DRF — JSON only in production
# ─────────────────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

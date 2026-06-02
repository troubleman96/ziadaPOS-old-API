"""
Development settings for Ziada POS backend.

Inherits from base.py and adds:
  - DEBUG = True
  - SQLite option OR PostgreSQL via DATABASE_URL
  - Verbose logging to console
  - django-extensions shell_plus support
  - Relaxed CORS for local frontend dev
"""

import dj_database_url
from decouple import config

from .base import *  # noqa: F401, F403 — intentional wildcard import

# ─────────────────────────────────────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────────────────────────────────────

DEBUG = True

# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

# Falls back to a local SQLite DB if DATABASE_URL is not set.
# For production-parity, set DATABASE_URL=postgres://... in .env
DATABASES = {
    "default": dj_database_url.config(
        default=config(
            "DATABASE_URL",
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",  # noqa: F405
        ),
        conn_max_age=600,
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# Email — print to console in dev, no need for real SMTP
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ─────────────────────────────────────────────────────────────────────────────
# Logging — verbose for development
# ─────────────────────────────────────────────────────────────────────────────

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
    "loggers": {
        # Quiet down noisy Django internals in dev
        "django.db.backends": {
            "level": "WARNING",
        },
        # Show our app logs at DEBUG level
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# CORS — allow all origins in development for convenience
# ─────────────────────────────────────────────────────────────────────────────

# Override base.py's strict CORS with dev-friendly open setting
CORS_ALLOW_ALL_ORIGINS = True

# ─────────────────────────────────────────────────────────────────────────────
# DRF — show browsable API in dev
# ─────────────────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405 — merge with base config
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # Browsable API only in dev — remove in production for performance
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

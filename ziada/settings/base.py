"""
Base Django settings for Ziada POS backend.

These settings are shared by ALL environments (development, staging, production).
Environment-specific settings live in development.py / production.py and
IMPORT from this file.

Key architectural decisions:
  - Custom User model (accounts.User) — must be set before first migration
  - Multi-tenant via Organisation → Store hierarchy
  - JWT authentication (no session cookies for API)
  - All monetary values stored in integer cents (TZS has no sub-units)
  - PostgreSQL as the only supported database
"""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config  # reads .env file

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

# Build paths like:  BASE_DIR / 'subdir'
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/

# ─────────────────────────────────────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────────────────────────────────────

SECRET_KEY = config("SECRET_KEY")

# ALLOWED_HOSTS is set per environment
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv(), default="localhost,127.0.0.1")

# ─────────────────────────────────────────────────────────────────────────────
# Application definition
# ─────────────────────────────────────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    # Django REST Framework — our primary API toolkit
    "rest_framework",
    # JWT authentication
    "rest_framework_simplejwt",
    # CORS headers — allows Next.js frontend to call the API
    "corsheaders",
    # Filter backend — ?field=value query param filtering
    "django_filters",
    # Developer utilities (shell_plus, etc.)
    "django_extensions",
]

LOCAL_APPS = [
    # Shared utilities: base model, standard response, custom exceptions
    "apps.core",
    # Users, organisations, stores, staff profiles
    "apps.accounts",
    # Products, categories, suppliers, stock levels
    "apps.inventory",
    # Sales transactions, line items, POS logic
    "apps.transactions",
    # Customer credit (madeni) management
    "apps.credits",
    # Customer profiles, segments, loyalty
    "apps.customers",
    # Aggregated analytics, daily summaries (signals wired in AnalyticsConfig.ready)
    "apps.analytics.apps.AnalyticsConfig",
    # AI chat, insights, OpenRouter integration
    # Note: AppConfig label is 'ai_app' to avoid collision with Python 'ai' namespace
    "apps.ai.apps.AIConfig",
    # Business reports: Sales Summary, Inventory Valuation, Tax Statement, Credit Aged Debtors
    "apps.reports",
    # Suppliers, deliveries, payments (AP / procurement)
    "apps.suppliers.apps.SuppliersConfig",
    # Stores management — multi-store KPIs, staff rosters, week analytics
    "apps.stores.apps.StoresConfig",
    # Internal notebook: memos, ideas, supplier notes (shared per store)
    "apps.notebook.apps.NotebookConfig",
    # Staff management: shifts, permissions, performance stats
    "apps.staff.apps.StaffConfig",
    # Subscription plans and billing management
    "apps.subscriptions.apps.SubscriptionsConfig",
    # API request tracking and admin dashboard analytics
    "apps.tracking.apps.TrackingConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

MIDDLEWARE = [
    # CORS must be first in the list so it fires before any response is sent
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # API request logging — must be last so request.user is populated by auth middleware
    "apps.tracking.middleware.RequestLogMiddleware",
]

# ─────────────────────────────────────────────────────────────────────────────
# URL configuration
# ─────────────────────────────────────────────────────────────────────────────

ROOT_URLCONF = "ziada.urls"

# ─────────────────────────────────────────────────────────────────────────────
# Templates (only needed for Django Admin)
# ─────────────────────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Include backend/templates/ so our admin/index.html override is found
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ziada.wsgi.application"
ASGI_APPLICATION = "ziada.asgi.application"

# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

# DATABASE_URL is parsed in environment-specific settings via dj-database-url.
# Default here is intentionally empty — it must be set in .env

# ─────────────────────────────────────────────────────────────────────────────
# Custom User Model
# ─────────────────────────────────────────────────────────────────────────────

# IMPORTANT: This must be defined BEFORE running the first migration.
# Changing it after migrations exist requires a full database reset.
AUTH_USER_MODEL = "accounts.User"

# ─────────────────────────────────────────────────────────────────────────────
# Password validation
# ─────────────────────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Internationalisation
# ─────────────────────────────────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"

# Tanzania timezone — critical for daily summaries and report date boundaries
TIME_ZONE = "Africa/Dar_es_Salaam"

USE_I18N = True
USE_TZ = True  # All DateTimeField values are stored as UTC in the DB

# ─────────────────────────────────────────────────────────────────────────────
# Static / Media files
# ─────────────────────────────────────────────────────────────────────────────

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─────────────────────────────────────────────────────────────────────────────
# Default primary key type
# ─────────────────────────────────────────────────────────────────────────────

# Use UUID primary keys in custom models (defined in base model).
# Django admin models still use integer PKs (that's fine).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─────────────────────────────────────────────────────────────────────────────
# Django REST Framework configuration
# ─────────────────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
    # JWT authentication as the default — no session cookies for API calls
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # All endpoints require authentication by default.
    # Individual views can override with AllowAny where needed (e.g. login).
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # Consistent pagination across all list endpoints
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsPagination",
    "PAGE_SIZE": 50,
    # Allow ?field=value filtering on list views
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    # Use our custom exception handler for standard error responses
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
}

# ─────────────────────────────────────────────────────────────────────────────
# JWT (Simple JWT) configuration
# ─────────────────────────────────────────────────────────────────────────────

SIMPLE_JWT = {
    # Short-lived access tokens — refresh without re-login
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", cast=int, default=60)
    ),
    # Longer-lived refresh token stored in the client
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", cast=int, default=7)
    ),
    # Issue a new refresh token on every refresh (sliding window)
    "ROTATE_REFRESH_TOKENS": True,
    # Invalidate old refresh token after rotation
    "BLACKLIST_AFTER_ROTATION": True,
    # Include token type claim for security
    "TOKEN_TYPE_CLAIM": "token_type",
    # Use our custom User model's primary key
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ─────────────────────────────────────────────────────────────────────────────
# CORS configuration
# ─────────────────────────────────────────────────────────────────────────────

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    cast=Csv(),
    default="http://localhost:3000,http://127.0.0.1:3000",
)

# Allow cookies/auth headers to be sent with cross-origin requests
CORS_ALLOW_CREDENTIALS = True

# ─────────────────────────────────────────────────────────────────────────────
# AI / OpenRouter configuration
# ─────────────────────────────────────────────────────────────────────────────

# OpenRouter API key — NEVER hardcode this, always read from .env
OPENROUTER_API_KEY = config("OPENROUTER_API_KEY", default="")

# Model for MVP: cheap + fast. GPT-4o-mini is excellent for structured data Q&A
OPENROUTER_MODEL = config("OPENROUTER_MODEL", default="openai/gpt-4o-mini")

# OpenRouter uses the OpenAI SDK but with a different base_url
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Branding sent with each request (helps OpenRouter's usage tracking)
OPENROUTER_SITE_URL = config("OPENROUTER_SITE_URL", default="http://localhost:3000")
OPENROUTER_SITE_NAME = config("OPENROUTER_SITE_NAME", default="Ziada POS")

# Maximum tokens to use for AI context window
# GPT-4o-mini supports 128k context — we use a fraction of that
AI_MAX_CONTEXT_TOKENS = 4000

# ─────────────────────────────────────────────────────────────────────────────
# Ziada application-level constants
# ─────────────────────────────────────────────────────────────────────────────

# Tanzania VAT rate (18%) — used in transaction calculations
TZ_VAT_RATE = 0.18

# Default currency code for display purposes
DEFAULT_CURRENCY = "TZS"

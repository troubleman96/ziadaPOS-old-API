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
    # S3-compatible object storage (MinIO for product images, etc.)
    "storages",
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
    # Business expense tracking
    "apps.expenses.apps.ExpensesConfig",
    # Store reviews — star ratings shown on landing page
    "apps.reviews.apps.ReviewsConfig",
    # Email notifications: welcome, confirmation, daily sales report
    "apps.notifications.apps.NotificationsConfig",
    # APScheduler job store
    "django_apscheduler",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

MIDDLEWARE = [
    # CORS must be first in the list so it fires before any response is sent
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves STATIC_ROOT directly — no nginx alias needed
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Subscription gate — disabled while the app is pre-launch. The trial-fee /
    # paywall flow (apps/subscriptions/middleware.py) is built but not enforced
    # yet, so new users can register and use the app freely. Re-enable this line
    # once the real subscription/billing model ships.
    # "apps.subscriptions.middleware.SubscriptionAccessMiddleware",
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

# Static files are always served by WhiteNoise (via gunicorn) with compression +
# far-future cache headers baked into hashed filenames — independent of whether
# MEDIA is on MinIO or local disk (see STORAGES["default"] below).
_STATICFILES_STORAGE = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# ── Object Storage (MinIO) ────────────────────────────────────────────────────
# When USE_MINIO=True, uploaded files (product images, etc.) are stored in the
# MinIO bucket instead of the local filesystem.  MinIO speaks the S3 protocol,
# so django-storages / boto3 handles it natively.
#
# Server-side requirement: the Nginx config on media.camelcreatives.com must
# proxy S3 API requests (port 9000) — see deploy.md § MinIO.
USE_MINIO = config("USE_MINIO", cast=bool, default=False)

if USE_MINIO:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "bucket_name":       config("MINIO_BUCKET_NAME", default="ziada"),
                "access_key":        config("MINIO_ACCESS_KEY"),
                "secret_key":        config("MINIO_SECRET_KEY"),
                "endpoint_url":      config("MINIO_ENDPOINT_URL"),
                "region_name":       config("MINIO_REGION", default="us-east-1"),
                "addressing_style":  "path",   # MinIO requires path-style (not virtual-hosted)
                "default_acl":       "public-read",
                "querystring_auth":  False,    # Public bucket — no signed URLs
                "file_overwrite":    False,    # Preserve original filenames with uuid suffix
                "object_parameters": {"CacheControl": "max-age=86400"},
            },
        },
        "staticfiles": _STATICFILES_STORAGE,
    }
    # Media files are served directly from MinIO (path-style URL)
    _bucket   = config("MINIO_BUCKET_NAME", default="ziada")
    _endpoint = config("MINIO_ENDPOINT_URL", default="https://media.camelcreatives.com")
    MEDIA_URL  = f"{_endpoint.rstrip('/')}/{_bucket}/"
    MEDIA_ROOT = ""   # Not used when MinIO is active
else:
    MEDIA_URL  = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": _STATICFILES_STORAGE,
    }

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
# AI / Ngamia configuration
# ─────────────────────────────────────────────────────────────────────────────

# Ngamia API key — NEVER hardcode this, always read from .env.
# Ngamia is an OpenAI-compatible API gateway with TZS billing via mobile money.
# Docs: https://docs.ngamia.cc
NGAMIA_API_KEY = config("NGAMIA_API_KEY", default="")

# Model string in provider/model_code format (fetch live list from GET /v1/models).
# Using OpenRouter's GPT-4o-mini via Ngamia: cheap, fast, multilingual.
NGAMIA_MODEL = config("NGAMIA_MODEL", default="openrouter/openai/gpt-4o-mini")

# Ngamia uses the OpenAI SDK but with a different base_url.
# Note the /v1 suffix — the SDK appends the rest of the path itself.
NGAMIA_BASE_URL = "https://api.ngamia.cc/v1"

# Maximum tokens to use for AI context window
AI_MAX_CONTEXT_TOKENS = 4000

# ─────────────────────────────────────────────────────────────────────────────
# SMS — SendAfrica (https://docs.sendafrica.online)
# ─────────────────────────────────────────────────────────────────────────────

# The platform's OWN SendAfrica key — used only to send auth OTPs (phone
# verification) to our users. Per-organisation SMS (credit reminders, ad-hoc
# customer messages) uses each org's own key (Organisation.sendafrica_api_key,
# set in Settings → Integrations), never this one.
SENDAFRICA_PLATFORM_API_KEY = config("SENDAFRICA_PLATFORM_API_KEY", default="")

# ─────────────────────────────────────────────────────────────────────────────
# Email (ZohoMail SMTP)
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST          = config("EMAIL_HOST",          default="smtp.zoho.com")
EMAIL_PORT          = config("EMAIL_PORT",          cast=int, default=587)
EMAIL_USE_TLS       = config("EMAIL_USE_TLS",       cast=bool, default=True)
EMAIL_USE_SSL       = config("EMAIL_USE_SSL",       cast=bool, default=False)
EMAIL_HOST_USER     = config("EMAIL_HOST_USER",     default="noreply@ziadapos.com")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL  = config("DEFAULT_FROM_EMAIL",  default="Ziada POS <noreply@ziadapos.com>")
SERVER_EMAIL        = config("SERVER_EMAIL",        default="noreply@ziadapos.com")

# Public site URL used in email links
SITE_URL = config("SITE_URL", default="https://app.ziadapos.com")

# Daily sales report schedule (Africa/Dar_es_Salaam, 24h clock)
DAILY_REPORT_HOUR   = config("DAILY_REPORT_HOUR",   cast=int, default=22)
DAILY_REPORT_MINUTE = config("DAILY_REPORT_MINUTE", cast=int, default=0)

# ─────────────────────────────────────────────────────────────────────────────
# APScheduler
# ─────────────────────────────────────────────────────────────────────────────

APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"
APSCHEDULER_RUN_NOW_TIMEOUT = 25  # seconds

# ─────────────────────────────────────────────────────────────────────────────
# Ziada application-level constants
# ─────────────────────────────────────────────────────────────────────────────

# Tanzania VAT rate (18%) — used in transaction calculations
TZ_VAT_RATE = 0.18

# Default currency code for display purposes
DEFAULT_CURRENCY = "TZS"

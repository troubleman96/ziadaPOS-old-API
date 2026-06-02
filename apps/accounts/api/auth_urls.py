"""
apps/accounts/api/auth_urls.py

JWT Authentication URL routes.
Mounted at: /api/v1/auth/

Endpoints:
  POST /api/v1/auth/login/         → obtain access + refresh tokens
  POST /api/v1/auth/refresh/       → get a new access token using refresh
  POST /api/v1/auth/verify/        → verify a token is still valid
"""

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,   # POST credentials → returns access + refresh tokens
    TokenRefreshView,       # POST refresh token → returns new access token
    TokenVerifyView,        # POST token → 200 if valid, 401 if not
)

urlpatterns = [
    # Login — POST { username, password } → { access, refresh }
    path("login/",   TokenObtainPairView.as_view(),  name="token_obtain_pair"),

    # Refresh — POST { refresh } → { access }
    path("refresh/", TokenRefreshView.as_view(),     name="token_refresh"),

    # Verify — POST { token } → 200 OK or 401
    path("verify/",  TokenVerifyView.as_view(),      name="token_verify"),
]

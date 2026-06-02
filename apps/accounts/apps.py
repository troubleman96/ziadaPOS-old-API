from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """
    Accounts app: manages users, organisations, stores, and staff profiles.
    This is the auth foundation — every other app depends on it.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts"

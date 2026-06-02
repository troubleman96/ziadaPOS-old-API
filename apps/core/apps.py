from django.apps import AppConfig


class CoreConfig(AppConfig):
    """
    Core app configuration.
    Provides shared base classes, response helpers, and utilities used by
    every other app in the project.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

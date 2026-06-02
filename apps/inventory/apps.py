from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    verbose_name = "Inventory"

    def ready(self):
        # Import signals so they register when the app loads
        import apps.inventory.signals  # noqa: F401

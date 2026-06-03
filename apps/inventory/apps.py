from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    verbose_name = "Inventory"

    def ready(self):
        import apps.inventory.signals  # noqa: F401

        from django.db.models.signals import post_migrate
        post_migrate.connect(_seed_global_categories_on_migrate, sender=self)


def _seed_global_categories_on_migrate(sender, **kwargs):
    """Auto-seed global categories after every migration run (idempotent)."""
    try:
        from apps.inventory.models import Category
        from apps.inventory.management.commands.seed_global_categories import GLOBAL_CATEGORIES

        for name, sort_order in GLOBAL_CATEGORIES:
            Category.objects.update_or_create(
                name=name,
                defaults={"sort_order": sort_order, "is_global": True},
            )
    except Exception:
        pass

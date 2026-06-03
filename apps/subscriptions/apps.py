from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subscriptions"
    verbose_name = "Subscriptions"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_seed_plans_on_migrate, sender=self)


def _seed_plans_on_migrate(sender, **kwargs):
    """
    Auto-seed the three default subscription plans after every migration run.
    Uses update_or_create so it's fully idempotent — safe to run on every deploy.
    """
    try:
        from apps.subscriptions.models import SubscriptionPlan
        from apps.subscriptions.management.commands.seed_plans import PLANS

        for plan_data in PLANS:
            data = dict(plan_data)
            slug = data.pop("slug")
            SubscriptionPlan.objects.update_or_create(slug=slug, defaults=data)
    except Exception:
        # Silently skip during initial migrations before the table exists
        pass

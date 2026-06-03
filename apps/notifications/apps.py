from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self):
        # Start the APScheduler background job (daily sales report at 22:00 EAT)
        # Guard: only start once (not in migrations, tests, or the reloader child process)
        import os
        import sys

        running_tests   = "test" in sys.argv
        running_migrate = "migrate" in sys.argv or "makemigrations" in sys.argv
        is_reloader_child = os.environ.get("RUN_MAIN") != "true"

        # In the Django dev-server, only the main process (RUN_MAIN=true) should schedule.
        # In production (gunicorn/uwsgi), skip the reloader guard — just start once.
        dev_server = "runserver" in sys.argv

        if running_tests or running_migrate:
            return

        if dev_server and is_reloader_child:
            return

        try:
            from .scheduler import start_scheduler
            start_scheduler()
        except Exception:
            pass  # Never crash Django startup due to scheduler errors

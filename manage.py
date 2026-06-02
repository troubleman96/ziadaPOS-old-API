#!/usr/bin/env python
"""
Django's command-line utility for administrative tasks.
Run with:  python manage.py <command>
"""

import os
import sys


def main():
    """
    Entry point for all Django management commands.
    Reads DJANGO_SETTINGS_MODULE from the environment; defaults to
    the development settings file if not set.
    """
    # Default to development settings; override via environment for staging/prod
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ziada.settings.development")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

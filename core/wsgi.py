"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.management import call_command
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

application = get_wsgi_application()


def _run_startup_migrations():
    """
    Render free-tier deployments may start Gunicorn without running build.sh.
    Keep the PostgreSQL schema synced before the first request hits Django admin/API.
    """
    enabled = os.getenv("SYNCIN_RUN_MIGRATIONS_ON_STARTUP", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return

    if not (os.getenv("RENDER") or os.getenv("DATABASE_URL")):
        return

    call_command("migrate", interactive=False, verbosity=1)


_run_startup_migrations()

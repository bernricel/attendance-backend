"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

application = get_asgi_application()


def _run_startup_migrations():
    """
    Keep hosted databases synced even when the platform start command bypasses build.sh.
    """
    enabled = os.getenv("SYNCIN_RUN_MIGRATIONS_ON_STARTUP", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return

    if not (os.getenv("RENDER") or os.getenv("DATABASE_URL")):
        return

    call_command("migrate", interactive=False, verbosity=1)


_run_startup_migrations()

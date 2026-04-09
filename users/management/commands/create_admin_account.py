from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from users.models import User


class Command(BaseCommand):
    help = "Create or update an admin account for credential-based admin login."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Admin email address.")
        parser.add_argument("--password", required=True, help="Admin password.")
        parser.add_argument(
            "--username",
            required=False,
            default="",
            help="Optional admin login username (alternative to email).",
        )
        parser.add_argument("--first-name", required=False, default="Admin")
        parser.add_argument("--last-name", required=False, default="User")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        login_username = (options.get("username") or "").strip().lower() or None

        if login_username and User.objects.filter(login_username=login_username).exclude(email=email).exists():
            raise CommandError("That login username is already assigned to another user.")

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(f"Password validation failed: {'; '.join(exc.messages)}") from exc

        defaults = {
            "role": User.Role.ADMIN,
            "is_staff": True,
            "first_name": options["first_name"].strip() or "Admin",
            "last_name": options["last_name"].strip() or "User",
            "login_username": login_username,
        }

        user, created = User.objects.get_or_create(email=email, defaults=defaults)
        user.role = User.Role.ADMIN
        user.is_staff = True
        user.login_username = login_username
        user.first_name = defaults["first_name"]
        user.last_name = defaults["last_name"]
        user.set_password(password)
        user.save()

        status = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Admin account {status}: {user.email}"))

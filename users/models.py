from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager that uses email as the unique login identifier."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")

        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        FACULTY = "faculty", "Faculty"

    username = None
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=False, default="")
    last_name = models.CharField(max_length=150, blank=False, default="")
    school_id = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FACULTY)
    is_profile_complete = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def refresh_profile_completion(self, save=True):
        self.is_profile_complete = all(
            [
                self.first_name.strip(),
                self.last_name.strip(),
                self.school_id.strip(),
                self.department.strip(),
            ]
        )
        if save:
            self.save(update_fields=["is_profile_complete"])

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        self.is_profile_complete = all(
            [
                self.first_name.strip(),
                self.last_name.strip(),
                self.school_id.strip(),
                self.department.strip(),
            ]
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

import uuid

from django.conf import settings
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.name


class AttendanceSession(models.Model):
    class SessionType(models.TextChoices):
        CHECK_IN = "check-in", "Check-in"
        CHECK_OUT = "check-out", "Check-out"

    name = models.CharField(max_length=255)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    session_type = models.CharField(max_length=20, choices=SessionType.choices)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    qr_token = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_time",)

    def __str__(self):
        return f"{self.name} ({self.department.name})"


class AttendanceRecord(models.Model):
    class AttendanceType(models.TextChoices):
        CHECK_IN = "check-in", "Check-in"
        CHECK_OUT = "check-out", "Check-out"

    class Status(models.TextChoices):
        RECORDED = "recorded", "Recorded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    check_time = models.DateTimeField(auto_now_add=True)
    attendance_type = models.CharField(max_length=20, choices=AttendanceType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECORDED)
    signed_payload = models.TextField(blank=True, default="")
    signature = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-check_time",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "session"),
                name="unique_attendance_per_user_session",
            )
        ]

    def __str__(self):
        return f"{self.user.email} - {self.session.name}"

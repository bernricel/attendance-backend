import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

SESSION_TYPE_CHOICES = (
    ("check-in", "Check-in"),
    ("check-out", "Check-out"),
    ("mixed", "Mixed"),
)


class AttendanceSchedule(models.Model):
    class RecurrencePattern(models.TextChoices):
        WEEKDAYS = "weekdays", "Monday to Friday"
        MWF = "mwf", "MWF"
        TTH = "tth", "TTH"
        CUSTOM = "custom", "Custom"

    name = models.CharField(max_length=255)
    # Legacy field retained for backwards compatibility with existing dashboards.
    session_type = models.CharField(max_length=20, choices=SESSION_TYPE_CHOICES, default="mixed")
    department = models.CharField(max_length=150, blank=True, default="")
    # Scheduled session span for the class/workday.
    start_time = models.TimeField()
    end_time = models.TimeField()
    # Attendance-rule windows applied to each generated occurrence.
    check_in_start_time = models.TimeField()
    check_in_end_time = models.TimeField()
    late_threshold_time = models.TimeField()
    check_out_start_time = models.TimeField()
    check_out_end_time = models.TimeField()
    recurrence_pattern = models.CharField(max_length=20, choices=RecurrencePattern.choices)
    # For custom recurrence, weekdays are stored as comma-separated integers (0=Mon ... 4=Fri).
    custom_weekdays = models.CharField(max_length=64, blank=True, default="")
    start_date = models.DateField()
    end_date = models.DateField()
    qr_refresh_interval_seconds = models.PositiveIntegerField(default=30)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_attendance_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.name


class AttendanceSession(models.Model):
    class LifecycleStatus(models.TextChoices):
        UPCOMING = "UPCOMING", "Upcoming"
        ACTIVE = "ACTIVE", "Active"
        ENDED = "ENDED", "Ended"

    class SessionType(models.TextChoices):
        CHECK_IN = "check-in", "Check-in"
        CHECK_OUT = "check-out", "Check-out"
        MIXED = "mixed", "Mixed"

    name = models.CharField(max_length=255)
    # Mixed sessions expose both check-in and check-out windows in one occurrence.
    session_type = models.CharField(max_length=20, choices=SessionType.choices, default=SessionType.MIXED)
    department = models.CharField(max_length=150, blank=True, default="")
    # Scheduled session span.
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    # Rule-based attendance windows.
    check_in_start_time = models.DateTimeField()
    check_in_end_time = models.DateTimeField()
    late_threshold_time = models.DateTimeField()
    check_out_start_time = models.DateTimeField()
    check_out_end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    qr_token = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)
    # Security hardening: QR code token rotates periodically to reduce replay risk.
    qr_refresh_interval_seconds = models.PositiveIntegerField(default=30)
    qr_token_last_rotated_at = models.DateTimeField(default=timezone.now)
    parent_schedule = models.ForeignKey(
        "AttendanceSchedule",
        on_delete=models.SET_NULL,
        related_name="generated_sessions",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_time",)

    def get_lifecycle_status(self, reference_time=None):
        """
        Compute lifecycle status from server time.

        We intentionally derive this dynamically so recurring occurrences do not
        need scheduled background jobs just to move between UPCOMING/ACTIVE/ENDED.
        """
        now = reference_time or timezone.now()
        if now < self.start_time:
            return self.LifecycleStatus.UPCOMING
        if now > self.end_time:
            return self.LifecycleStatus.ENDED
        return self.LifecycleStatus.ACTIVE

    def is_accepting_attendance(self, reference_time=None):
        """Attendance is accepted only while ACTIVE and manually active."""
        return self.is_active and self.get_lifecycle_status(reference_time) == self.LifecycleStatus.ACTIVE

    def sync_active_flag_with_lifecycle(self, reference_time=None, save=True):
        """
        Automatically deactivate sessions after their end_time.

        This guarantees ended sessions are archived from an operational standpoint
        even if no explicit admin action is taken.
        """
        status = self.get_lifecycle_status(reference_time)
        changed = False
        if status == self.LifecycleStatus.ENDED and self.is_active:
            self.is_active = False
            changed = True
            if save:
                self.save(update_fields=["is_active"])
        return status, changed

    def get_qr_expiry_time(self):
        """Return the server timestamp when the current QR token expires."""
        return self.qr_token_last_rotated_at + timedelta(seconds=self.qr_refresh_interval_seconds)

    def is_qr_token_expired(self, reference_time=None):
        """Check whether the current QR token has passed its refresh interval."""
        now = reference_time or timezone.now()
        return now >= self.get_qr_expiry_time()

    def rotate_qr_token(self, reference_time=None, save=True):
        """
        Generate a new QR token and update the rotation timestamp.

        Notes:
        - Previous token becomes invalid after rotation.
        - Rotation time is tracked so the server can enforce token expiry.
        """
        now = reference_time or timezone.now()
        self.qr_token = uuid.uuid4().hex
        self.qr_token_last_rotated_at = now
        if save:
            self.save(update_fields=["qr_token", "qr_token_last_rotated_at"])
        return self.qr_token

    def __str__(self):
        return self.name


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
    is_late = models.BooleanField(default=False)
    signed_payload = models.TextField(blank=True, default="")
    signature = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-check_time",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "session", "attendance_type"),
                name="unique_attendance_per_user_session_type",
            )
        ]

    def __str__(self):
        return f"{self.user.email} - {self.session.name}"

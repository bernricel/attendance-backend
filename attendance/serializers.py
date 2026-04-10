from datetime import date, datetime

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession


class AttendanceSessionSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    attendance_count = serializers.SerializerMethodField()
    qr_token_expires_at = serializers.SerializerMethodField()
    lifecycle_status = serializers.SerializerMethodField()
    can_accept_attendance = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "department",
            "session_type",
            "start_time",
            "end_time",
            "check_in_start_time",
            "check_in_end_time",
            "late_threshold_time",
            "check_out_start_time",
            "check_out_end_time",
            "is_active",
            "lifecycle_status",
            "can_accept_attendance",
            "qr_token",
            "qr_refresh_interval_seconds",
            "qr_token_last_rotated_at",
            "qr_token_expires_at",
            "parent_schedule",
            "created_by_email",
            "attendance_count",
            "created_at",
        )

    def get_attendance_count(self, obj):
        annotated_count = getattr(obj, "attendance_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.attendance_records.count()

    def get_qr_token_expires_at(self, obj):
        return obj.get_qr_expiry_time()

    def get_lifecycle_status(self, obj):
        return obj.get_lifecycle_status()

    def get_can_accept_attendance(self, obj):
        return obj.is_accepting_attendance()


class CreateSessionSerializer(serializers.Serializer):
    """
    Unified input serializer for both single and recurring session creation.

    - is_recurring=False: expects start_time/end_time datetime fields.
    - is_recurring=True: expects recurrence fields and time-of-day fields.
    """

    # `title` is the preferred field for the new rule-based session structure.
    title = serializers.CharField(max_length=255, required=False, allow_blank=False)
    # Backward-compatible alias so existing clients are not immediately broken.
    name = serializers.CharField(max_length=255, required=False, allow_blank=False)
    department = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)
    qr_refresh_interval_seconds = serializers.IntegerField(required=False, min_value=1, default=30)

    is_recurring = serializers.BooleanField(required=False, default=False)

    # Single-session mode fields.
    session_date = serializers.DateField(required=False)

    # Shared rule windows (required for both single and recurring modes).
    scheduled_start_time = serializers.TimeField(required=False)
    scheduled_end_time = serializers.TimeField(required=False)
    check_in_start_time = serializers.TimeField(required=False)
    check_in_end_time = serializers.TimeField(required=False)
    late_threshold_time = serializers.TimeField(required=False)
    check_out_start_time = serializers.TimeField(required=False)
    check_out_end_time = serializers.TimeField(required=False)

    # Recurring mode date rule fields.
    recurrence_pattern = serializers.ChoiceField(
        choices=AttendanceSchedule.RecurrencePattern.choices,
        required=False,
    )
    recurrence_days = serializers.ListField(
        child=serializers.ChoiceField(choices=[0, 1, 2, 3, 4, 5, 6]),
        required=False,
        allow_empty=False,
    )
    recurrence_start_date = serializers.DateField(required=False)
    recurrence_end_date = serializers.DateField(required=False)
    def validate(self, attrs):
        title = attrs.get("title") or attrs.get("name")
        if not title:
            raise serializers.ValidationError("title is required.")
        attrs["name"] = title
        # CIT-only scope: department is system-defined, not selected in current UI.
        attrs["department"] = (getattr(settings, "DEFAULT_ATTENDANCE_DEPARTMENT", "CIT") or "CIT").strip()

        is_recurring = attrs.get("is_recurring", False)
        required_rule_fields = (
            "scheduled_start_time",
            "scheduled_end_time",
            "check_in_start_time",
            "check_in_end_time",
            "late_threshold_time",
            "check_out_start_time",
            "check_out_end_time",
        )
        missing_rule_fields = [field for field in required_rule_fields if not attrs.get(field)]
        if missing_rule_fields:
            raise serializers.ValidationError(
                f"Missing required attendance rule fields: {', '.join(missing_rule_fields)}."
            )

        if attrs["scheduled_start_time"] >= attrs["scheduled_end_time"]:
            raise serializers.ValidationError("scheduled_end_time must be later than scheduled_start_time.")
        if attrs["check_in_start_time"] >= attrs["check_in_end_time"]:
            raise serializers.ValidationError("check_in_end_time must be later than check_in_start_time.")
        if attrs["check_out_start_time"] >= attrs["check_out_end_time"]:
            raise serializers.ValidationError("check_out_end_time must be later than check_out_start_time.")
        if not (attrs["check_in_start_time"] <= attrs["late_threshold_time"] <= attrs["check_in_end_time"]):
            raise serializers.ValidationError("late_threshold_time must be within the check-in window.")

        if not is_recurring:
            if not attrs.get("session_date"):
                raise serializers.ValidationError("session_date is required for single session mode.")
            return attrs

        # Recurring mode validation.
        required_fields = (
            "recurrence_pattern",
            "recurrence_start_date",
            "recurrence_end_date",
        )
        missing = [field for field in required_fields if not attrs.get(field)]
        if missing:
            raise serializers.ValidationError(f"Missing required recurring fields: {', '.join(missing)}.")

        if attrs["recurrence_start_date"] > attrs["recurrence_end_date"]:
            raise serializers.ValidationError("recurrence_end_date must be on or after recurrence_start_date.")

        if (
            attrs["recurrence_pattern"] == AttendanceSchedule.RecurrencePattern.CUSTOM
            and not attrs.get("recurrence_days")
        ):
            raise serializers.ValidationError("recurrence_days must include at least one weekday for custom pattern.")

        return attrs

    def build_single_session_datetimes(self):
        """
        Build timezone-aware datetime windows for a single date occurrence.

        This keeps all derived datetime assembly in one place so view logic remains clear.
        """
        data = self.validated_data
        target_date = data["session_date"]
        tz_info = timezone.get_current_timezone()
        return {
            "start_time": timezone.make_aware(datetime.combine(target_date, data["scheduled_start_time"]), tz_info),
            "end_time": timezone.make_aware(datetime.combine(target_date, data["scheduled_end_time"]), tz_info),
            "check_in_start_time": timezone.make_aware(
                datetime.combine(target_date, data["check_in_start_time"]),
                tz_info,
            ),
            "check_in_end_time": timezone.make_aware(
                datetime.combine(target_date, data["check_in_end_time"]),
                tz_info,
            ),
            "late_threshold_time": timezone.make_aware(
                datetime.combine(target_date, data["late_threshold_time"]),
                tz_info,
            ),
            "check_out_start_time": timezone.make_aware(
                datetime.combine(target_date, data["check_out_start_time"]),
                tz_info,
            ),
            "check_out_end_time": timezone.make_aware(
                datetime.combine(target_date, data["check_out_end_time"]),
                tz_info,
            ),
        }


class AttendanceScheduleSerializer(serializers.ModelSerializer):
    generated_session_count = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    custom_weekdays = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSchedule
        fields = (
            "id",
            "name",
            "department",
            "session_type",
            "start_time",
            "end_time",
            "check_in_start_time",
            "check_in_end_time",
            "late_threshold_time",
            "check_out_start_time",
            "check_out_end_time",
            "recurrence_pattern",
            "custom_weekdays",
            "start_date",
            "end_date",
            "qr_refresh_interval_seconds",
            "created_by_email",
            "generated_session_count",
            "created_at",
        )

    def get_generated_session_count(self, obj):
        return obj.generated_sessions.count()

    def get_custom_weekdays(self, obj):
        if not obj.custom_weekdays:
            return []
        return [int(value) for value in obj.custom_weekdays.split(",") if value != ""]


class CreateScheduleSerializer(serializers.ModelSerializer):
    custom_weekdays = serializers.ListField(
        child=serializers.ChoiceField(choices=[0, 1, 2, 3, 4, 5, 6]),
        required=False,
        allow_empty=False,
    )
    qr_refresh_interval_seconds = serializers.IntegerField(required=False, min_value=1, default=30)

    class Meta:
        model = AttendanceSchedule
        fields = (
            "name",
            "department",
            "session_type",
            "start_time",
            "end_time",
            "check_in_start_time",
            "check_in_end_time",
            "late_threshold_time",
            "check_out_start_time",
            "check_out_end_time",
            "recurrence_pattern",
            "custom_weekdays",
            "start_date",
            "end_date",
            "qr_refresh_interval_seconds",
        )

    def validate(self, attrs):
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError("end_time must be later than start_time.")
        if attrs["check_in_start_time"] >= attrs["check_in_end_time"]:
            raise serializers.ValidationError("check_in_end_time must be later than check_in_start_time.")
        if attrs["check_out_start_time"] >= attrs["check_out_end_time"]:
            raise serializers.ValidationError("check_out_end_time must be later than check_out_start_time.")
        if not (attrs["check_in_start_time"] <= attrs["late_threshold_time"] <= attrs["check_in_end_time"]):
            raise serializers.ValidationError("late_threshold_time must be within the check-in window.")
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError("end_date must be on or after start_date.")

        recurrence = attrs["recurrence_pattern"]
        custom_weekdays = attrs.get("custom_weekdays", [])
        if recurrence == AttendanceSchedule.RecurrencePattern.CUSTOM and not custom_weekdays:
            raise serializers.ValidationError("custom_weekdays is required for custom recurrence.")
        return attrs

    def create(self, validated_data):
        custom_weekdays = validated_data.pop("custom_weekdays", [])
        custom_weekdays_text = ",".join(str(day) for day in sorted(set(custom_weekdays)))
        return AttendanceSchedule.objects.create(
            custom_weekdays=custom_weekdays_text,
            created_by=self.context["request"].user,
            **validated_data,
        )


class AttendanceRecordSerializer(serializers.ModelSerializer):
    session_name = serializers.CharField(source="session.name", read_only=True)
    session_type = serializers.CharField(source="session.session_type", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = AttendanceRecord
        # Include signed_payload + signature so records are auditable and verifiable.
        fields = (
            "id",
            "user_email",
            "user_first_name",
            "user_last_name",
            "session",
            "session_name",
            "session_type",
            "check_time",
            "attendance_type",
            "status",
            "is_late",
            "signed_payload",
            "signature",
        )
        read_only_fields = ("check_time", "status")


class ScanAttendanceSerializer(serializers.Serializer):
    qr_token = serializers.CharField(required=True, allow_blank=False)
    attendance_type = serializers.ChoiceField(
        choices=AttendanceRecord.AttendanceType.choices,
        required=False,
    )


class VerifySignatureSerializer(serializers.Serializer):
    # Simple input contract for /admin/verify-signature endpoint.
    attendance_record_id = serializers.IntegerField(required=True, min_value=1)


class FacultySessionPreviewSerializer(serializers.ModelSerializer):
    qr_refresh_interval_seconds = serializers.IntegerField(read_only=True)
    lifecycle_status = serializers.SerializerMethodField()
    can_accept_attendance = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "department",
            "session_type",
            "start_time",
            "end_time",
            "check_in_start_time",
            "check_in_end_time",
            "late_threshold_time",
            "check_out_start_time",
            "check_out_end_time",
            "is_active",
            "lifecycle_status",
            "can_accept_attendance",
            "qr_token",
            "qr_refresh_interval_seconds",
        )

    def get_lifecycle_status(self, obj):
        return obj.get_lifecycle_status()

    def get_can_accept_attendance(self, obj):
        return obj.is_accepting_attendance()


class AttendanceByDateQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=True)

    def validate_date(self, value: date):
        if value > timezone.localdate():
            raise serializers.ValidationError("Date cannot be in the future.")
        return value


def get_session_queryset_with_counts():
    return AttendanceSession.objects.select_related("created_by").annotate(
        attendance_count=Count("attendance_records")
    )

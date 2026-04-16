from datetime import date, datetime, time

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
            "enable_check_in_window",
            "enable_check_out_window",
            "session_end_time",
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

    - is_recurring=False: expects session_date and optional time controls.
    - is_recurring=True: expects recurrence fields and optional time controls.
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

    # Shared rule windows.
    scheduled_start_time = serializers.TimeField(required=False, allow_null=True)
    # Backward-compatible legacy alias. New clients should use session_end_time instead.
    scheduled_end_time = serializers.TimeField(required=False, allow_null=True)
    check_in_start_time = serializers.TimeField(required=False, allow_null=True)
    check_in_end_time = serializers.TimeField(required=False, allow_null=True)
    late_threshold_time = serializers.TimeField(required=False, allow_null=True)
    check_out_start_time = serializers.TimeField(required=False, allow_null=True)
    check_out_end_time = serializers.TimeField(required=False, allow_null=True)
    enable_check_in_window = serializers.BooleanField(required=False, default=False)
    enable_check_out_window = serializers.BooleanField(required=False, default=False)
    session_end_time = serializers.TimeField(required=False, allow_null=True)

    # Recurring mode date rule fields.
    recurrence_pattern = serializers.ChoiceField(
        choices=AttendanceSchedule.RecurrencePattern.choices,
        required=False,
    )
    recurrence_days = serializers.ListField(
        child=serializers.ChoiceField(choices=[0, 1, 2, 3, 4, 5, 6]),
        required=False,
        # Allow empty input so non-custom recurrence can be derived server-side.
        allow_empty=True,
    )
    recurrence_start_date = serializers.DateField(required=False)
    recurrence_end_date = serializers.DateField(required=False)

    @staticmethod
    def _resolve_pattern_days(recurrence_pattern):
        if recurrence_pattern == AttendanceSchedule.RecurrencePattern.WEEKDAYS:
            return [0, 1, 2, 3, 4]
        if recurrence_pattern == AttendanceSchedule.RecurrencePattern.MWF:
            return [0, 2, 4]
        if recurrence_pattern == AttendanceSchedule.RecurrencePattern.TTH:
            return [1, 3]
        return []

    def validate(self, attrs):
        title = attrs.get("title") or attrs.get("name")
        if not title:
            raise serializers.ValidationError("title is required.")
        attrs["name"] = title
        # CIT-only scope: department is system-defined, not selected in current UI.
        attrs["department"] = (getattr(settings, "DEFAULT_ATTENDANCE_DEPARTMENT", "CIT") or "CIT").strip()

        is_recurring = attrs.get("is_recurring", False)
        has_explicit_check_in_toggle = "enable_check_in_window" in self.initial_data
        has_explicit_check_out_toggle = "enable_check_out_window" in self.initial_data
        if not has_explicit_check_in_toggle:
            attrs["enable_check_in_window"] = bool(
                attrs.get("check_in_start_time") or attrs.get("check_in_end_time")
            )
        if not has_explicit_check_out_toggle:
            attrs["enable_check_out_window"] = bool(
                attrs.get("check_out_start_time") or attrs.get("check_out_end_time")
            )

        effective_start_time = (
            attrs.get("scheduled_start_time")
            or attrs.get("check_in_start_time")
            or attrs.get("check_out_start_time")
            or attrs.get("late_threshold_time")
            or time(0, 0)
        )
        attrs["effective_start_time"] = effective_start_time

        # Single overall optional ending control, with legacy fallback for older clients.
        overall_end_time = attrs.get("session_end_time")
        if overall_end_time is None and "session_end_time" not in self.initial_data:
            overall_end_time = attrs.get("scheduled_end_time")
        attrs["session_end_time"] = overall_end_time
        if overall_end_time and overall_end_time <= effective_start_time:
            raise serializers.ValidationError("session_end_time must be later than the effective session start time.")

        if attrs["enable_check_in_window"]:
            if not attrs.get("check_in_start_time"):
                raise serializers.ValidationError(
                    "check_in_start_time is required when check-in window is enabled."
                )
            if attrs.get("check_in_end_time") and attrs["check_in_start_time"] >= attrs["check_in_end_time"]:
                raise serializers.ValidationError("check_in_end_time must be later than check_in_start_time.")
            if attrs.get("late_threshold_time") and attrs["late_threshold_time"] < attrs["check_in_start_time"]:
                raise serializers.ValidationError(
                    "late_threshold_time must be on or after check_in_start_time."
                )
            if (
                attrs.get("late_threshold_time")
                and
                attrs.get("check_in_end_time")
                and attrs["late_threshold_time"] > attrs["check_in_end_time"]
            ):
                raise serializers.ValidationError("late_threshold_time must be within the check-in window.")
        else:
            attrs["check_in_start_time"] = None
            attrs["check_in_end_time"] = None

        if attrs["enable_check_out_window"]:
            if not attrs.get("check_out_start_time"):
                raise serializers.ValidationError(
                    "check_out_start_time is required when check-out window is enabled."
                )
            if attrs.get("check_out_end_time") and attrs["check_out_start_time"] >= attrs["check_out_end_time"]:
                raise serializers.ValidationError("check_out_end_time must be later than check_out_start_time.")
        else:
            attrs["check_out_start_time"] = None
            attrs["check_out_end_time"] = None

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

        recurrence_pattern = attrs["recurrence_pattern"]
        recurrence_days = sorted(set(attrs.get("recurrence_days", [])))

        if recurrence_pattern == AttendanceSchedule.RecurrencePattern.CUSTOM and not recurrence_days:
            raise serializers.ValidationError("recurrence_days must include at least one weekday for custom pattern.")

        # Normalize recurrence_days so recurring generation always has concrete weekdays.
        attrs["recurrence_days"] = (
            recurrence_days
            if recurrence_pattern == AttendanceSchedule.RecurrencePattern.CUSTOM
            else self._resolve_pattern_days(recurrence_pattern)
        )

        return attrs

    def build_single_session_datetimes(self):
        """
        Build timezone-aware datetime windows for a single date occurrence.

        This keeps all derived datetime assembly in one place so view logic remains clear.
        """
        data = self.validated_data
        target_date = data["session_date"]
        tz_info = timezone.get_current_timezone()

        def _to_aware_datetime(time_value):
            if not time_value:
                return None
            return timezone.make_aware(datetime.combine(target_date, time_value), tz_info)

        start_time_value = data.get("effective_start_time") or time(0, 0)
        session_end_time_value = data.get("session_end_time")
        start_dt = _to_aware_datetime(start_time_value)
        session_end_dt = _to_aware_datetime(session_end_time_value)

        return {
            "start_time": start_dt,
            "end_time": session_end_dt or start_dt,
            "session_end_time": session_end_dt,
            "check_in_start_time": _to_aware_datetime(data.get("check_in_start_time")),
            "check_in_end_time": _to_aware_datetime(data.get("check_in_end_time")),
            "late_threshold_time": _to_aware_datetime(data.get("late_threshold_time")),
            "check_out_start_time": _to_aware_datetime(data.get("check_out_start_time")),
            "check_out_end_time": _to_aware_datetime(data.get("check_out_end_time")),
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
            "enable_check_in_window",
            "enable_check_out_window",
            "session_end_time",
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


class AdminFacultyAttendanceQuerySerializer(serializers.Serializer):
    faculty_id = serializers.IntegerField(required=False, min_value=1)


class AdminSessionDeleteSerializer(serializers.Serializer):
    password = serializers.CharField(required=True, allow_blank=False, trim_whitespace=False)


def get_session_queryset_with_counts():
    return AttendanceSession.objects.select_related("created_by").annotate(
        attendance_count=Count("attendance_records")
    )

from datetime import date

from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession


class AttendanceSessionSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    attendance_count = serializers.SerializerMethodField()
    qr_token_expires_at = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "session_type",
            "start_time",
            "end_time",
            "is_active",
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


class CreateSessionSerializer(serializers.Serializer):
    """
    Unified input serializer for both single and recurring session creation.

    - is_recurring=False: expects start_time/end_time datetime fields.
    - is_recurring=True: expects recurrence fields and time-of-day fields.
    """

    name = serializers.CharField(max_length=255)
    session_type = serializers.ChoiceField(choices=AttendanceSession.SessionType.choices)
    is_active = serializers.BooleanField(required=False, default=True)
    qr_refresh_interval_seconds = serializers.IntegerField(required=False, min_value=1, default=30)

    is_recurring = serializers.BooleanField(required=False, default=False)

    # Single-session mode fields.
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)

    # Recurring mode fields.
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
    recurrence_start_time = serializers.TimeField(required=False)
    recurrence_end_time = serializers.TimeField(required=False)

    def validate(self, attrs):
        is_recurring = attrs.get("is_recurring", False)

        if not is_recurring:
            if not attrs.get("start_time") or not attrs.get("end_time"):
                raise serializers.ValidationError("start_time and end_time are required for single session mode.")
            if attrs["start_time"] >= attrs["end_time"]:
                raise serializers.ValidationError("end_time must be later than start_time.")
            return attrs

        # Recurring mode validation.
        required_fields = (
            "recurrence_pattern",
            "recurrence_start_date",
            "recurrence_end_date",
            "recurrence_start_time",
            "recurrence_end_time",
        )
        missing = [field for field in required_fields if not attrs.get(field)]
        if missing:
            raise serializers.ValidationError(f"Missing required recurring fields: {', '.join(missing)}.")

        if attrs["recurrence_start_date"] > attrs["recurrence_end_date"]:
            raise serializers.ValidationError("recurrence_end_date must be on or after recurrence_start_date.")

        if attrs["recurrence_start_time"] >= attrs["recurrence_end_time"]:
            raise serializers.ValidationError("recurrence_end_time must be later than recurrence_start_time.")

        if (
            attrs["recurrence_pattern"] == AttendanceSchedule.RecurrencePattern.CUSTOM
            and not attrs.get("recurrence_days")
        ):
            raise serializers.ValidationError("recurrence_days must include at least one weekday for custom pattern.")

        return attrs


class AttendanceScheduleSerializer(serializers.ModelSerializer):
    generated_session_count = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    custom_weekdays = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSchedule
        fields = (
            "id",
            "name",
            "session_type",
            "start_time",
            "end_time",
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
            "session_type",
            "start_time",
            "end_time",
            "recurrence_pattern",
            "custom_weekdays",
            "start_date",
            "end_date",
            "qr_refresh_interval_seconds",
        )

    def validate(self, attrs):
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError("end_time must be later than start_time.")
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
    attendance_record_id = serializers.IntegerField(required=True, min_value=1)


class FacultySessionPreviewSerializer(serializers.ModelSerializer):
    qr_refresh_interval_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "session_type",
            "start_time",
            "end_time",
            "is_active",
            "qr_token",
            "qr_refresh_interval_seconds",
        )


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

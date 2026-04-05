from datetime import date

from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSession, Department


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name")


class AttendanceSessionSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    attendance_count = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "department",
            "session_type",
            "start_time",
            "end_time",
            "is_active",
            "qr_token",
            "created_by_email",
            "attendance_count",
            "created_at",
        )

    def get_attendance_count(self, obj):
        annotated_count = getattr(obj, "attendance_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.attendance_records.count()


class CreateSessionSerializer(serializers.ModelSerializer):
    department = serializers.CharField(write_only=True)

    class Meta:
        model = AttendanceSession
        fields = ("name", "department", "session_type", "start_time", "end_time", "is_active")

    def validate(self, attrs):
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError("end_time must be later than start_time.")
        return attrs

    def create(self, validated_data):
        department_name = validated_data.pop("department").strip()
        department, _ = Department.objects.get_or_create(name=department_name)

        return AttendanceSession.objects.create(
            department=department,
            created_by=self.context["request"].user,
            **validated_data,
        )


class AttendanceRecordSerializer(serializers.ModelSerializer):
    session_name = serializers.CharField(source="session.name", read_only=True)
    session_type = serializers.CharField(source="session.session_type", read_only=True)
    department_name = serializers.CharField(source="session.department.name", read_only=True)
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
            "department_name",
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
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "name",
            "department_name",
            "session_type",
            "start_time",
            "end_time",
            "is_active",
            "qr_token",
        )


class AttendanceByDateQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=True)

    def validate_date(self, value: date):
        if value > timezone.localdate():
            raise serializers.ValidationError("Date cannot be in the future.")
        return value


def get_session_queryset_with_counts():
    return AttendanceSession.objects.select_related("department", "created_by").annotate(
        attendance_count=Count("attendance_records")
    )

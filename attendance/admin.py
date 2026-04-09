from django.contrib import admin

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession


@admin.register(AttendanceSchedule)
class AttendanceScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "session_type",
        "recurrence_pattern",
        "start_date",
        "end_date",
        "created_by",
    )
    list_filter = ("session_type", "recurrence_pattern")
    search_fields = ("name", "created_by__email")


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "session_type",
        "start_time",
        "end_time",
        "is_active",
        "parent_schedule",
        "created_by",
    )
    list_filter = ("session_type", "is_active", "parent_schedule")
    search_fields = ("name", "created_by__email", "qr_token")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "session",
        "attendance_type",
        "status",
        "check_time",
    )
    list_filter = ("attendance_type", "status")
    search_fields = ("user__email", "session__name", "session__qr_token")

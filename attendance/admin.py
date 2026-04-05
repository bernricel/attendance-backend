from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession, Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "department",
        "session_type",
        "start_time",
        "end_time",
        "is_active",
        "created_by",
    )
    list_filter = ("session_type", "is_active", "department")
    search_fields = ("name", "department__name", "created_by__email", "qr_token")


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
    list_filter = ("attendance_type", "status", "session__department")
    search_fields = ("user__email", "session__name", "session__qr_token")

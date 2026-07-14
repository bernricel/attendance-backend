from django.contrib import admin

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession, Department, Program, Section


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "department", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "department")
    search_fields = ("name", "code", "department__name")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "program", "is_active", "is_archived", "created_at", "updated_at")
    list_filter = ("is_active", "is_archived", "program__department", "program")
    search_fields = ("name", "program__code", "program__name", "program__department__name")


@admin.register(AttendanceSchedule)
class AttendanceScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "department",
        "session_type",
        "recurrence_pattern",
        "start_date",
        "end_date",
        "created_by",
    )
    list_filter = ("session_type", "recurrence_pattern")
    search_fields = ("name", "department", "created_by__email")


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
        "parent_schedule",
        "created_by",
    )
    list_filter = ("session_type", "is_active", "parent_schedule")
    search_fields = ("name", "department", "created_by__email", "qr_token")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "session",
        "attendance_type",
        "is_late",
        "status",
        "check_time",
    )
    list_filter = ("attendance_type", "status")
    search_fields = ("user__email", "session__name", "session__qr_token")

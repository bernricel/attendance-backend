import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0003_remove_attendancesession_department_delete_department"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("session_type", models.CharField(choices=[("check-in", "Check-in"), ("check-out", "Check-out")], max_length=20)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("recurrence_pattern", models.CharField(choices=[("weekdays", "Monday to Friday"), ("mwf", "MWF"), ("tth", "TTH"), ("custom", "Custom")], max_length=20)),
                ("custom_weekdays", models.CharField(blank=True, default="", max_length=64)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("qr_refresh_interval_seconds", models.PositiveIntegerField(default=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_attendance_schedules", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="parent_schedule",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="generated_sessions", to="attendance.attendanceschedule"),
        ),
    ]

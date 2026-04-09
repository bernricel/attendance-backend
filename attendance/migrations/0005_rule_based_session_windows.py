from datetime import datetime, time, timezone

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0004_attendanceschedule_and_parent_schedule"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="attendanceschedule",
            name="check_in_end_time",
            field=models.TimeField(default=time(8, 15)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="check_in_start_time",
            field=models.TimeField(default=time(7, 30)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="check_out_end_time",
            field=models.TimeField(default=time(17, 30)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="check_out_start_time",
            field=models.TimeField(default=time(16, 30)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="department",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="late_threshold_time",
            field=models.TimeField(default=time(8, 0)),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="attendanceschedule",
            name="session_type",
            field=models.CharField(
                choices=[("check-in", "Check-in"), ("check-out", "Check-out"), ("mixed", "Mixed")],
                default="mixed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="check_in_end_time",
            field=models.DateTimeField(default=datetime(2026, 1, 1, 8, 15, tzinfo=timezone.utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="check_in_start_time",
            field=models.DateTimeField(default=datetime(2026, 1, 1, 7, 30, tzinfo=timezone.utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="check_out_end_time",
            field=models.DateTimeField(default=datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="check_out_start_time",
            field=models.DateTimeField(default=datetime(2026, 1, 1, 16, 30, tzinfo=timezone.utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="department",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="late_threshold_time",
            field=models.DateTimeField(default=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="attendancesession",
            name="session_type",
            field=models.CharField(
                choices=[("check-in", "Check-in"), ("check-out", "Check-out"), ("mixed", "Mixed")],
                default="mixed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="is_late",
            field=models.BooleanField(default=False),
        ),
        migrations.RemoveConstraint(
            model_name="attendancerecord",
            name="unique_attendance_per_user_session",
        ),
        migrations.AddConstraint(
            model_name="attendancerecord",
            constraint=models.UniqueConstraint(
                fields=("user", "session", "attendance_type"),
                name="unique_attendance_per_user_session_type",
            ),
        ),
    ]

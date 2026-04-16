from django.db import migrations, models


def _backfill_existing_sessions(apps, schema_editor):
    AttendanceSession = apps.get_model("attendance", "AttendanceSession")
    AttendanceSession.objects.filter(enable_check_in_window=False).update(enable_check_in_window=True)
    AttendanceSession.objects.filter(enable_check_out_window=False).update(enable_check_out_window=True)
    AttendanceSession.objects.filter(session_end_time__isnull=True).update(session_end_time=models.F("end_time"))


def _noop_reverse(apps, schema_editor):
    # Backward migration should keep existing data untouched.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0005_rule_based_session_windows"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendancesession",
            name="check_in_end_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="attendancesession",
            name="check_in_start_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="attendancesession",
            name="check_out_end_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="attendancesession",
            name="check_out_start_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="enable_check_in_window",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="enable_check_out_window",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="session_end_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(_backfill_existing_sessions, _noop_reverse),
    ]

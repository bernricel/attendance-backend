from django.db import migrations, models
import django.db.models.deletion


DEFAULT_DEPARTMENTS = [
    "Human Resources",
    "Accounting",
    "Finance",
    "Information Technology",
    "Registrar",
]


def seed_departments_and_migrate_refs(apps, schema_editor):
    Department = apps.get_model("attendance", "Department")
    AttendanceSession = apps.get_model("attendance", "AttendanceSession")
    AttendanceSchedule = apps.get_model("attendance", "AttendanceSchedule")

    department_by_name = {}

    for name in DEFAULT_DEPARTMENTS:
        department, _created = Department.objects.get_or_create(name=name)
        department_by_name[name.strip().lower()] = department

    legacy_names = set()
    legacy_names.update(
        value.strip()
        for value in AttendanceSession.objects.exclude(legacy_department="").values_list("legacy_department", flat=True)
        if value and value.strip()
    )
    legacy_names.update(
        value.strip()
        for value in AttendanceSchedule.objects.exclude(legacy_department="").values_list("legacy_department", flat=True)
        if value and value.strip()
    )

    for name in sorted(legacy_names):
        department, _created = Department.objects.get_or_create(name=name)
        department_by_name[name.lower()] = department

    for session in AttendanceSession.objects.all():
        legacy_name = (session.legacy_department or "").strip()
        session.department = department_by_name.get(legacy_name.lower()) if legacy_name else None
        session.save(update_fields=["department"])

    for schedule in AttendanceSchedule.objects.all():
        legacy_name = (schedule.legacy_department or "").strip()
        schedule.department = department_by_name.get(legacy_name.lower()) if legacy_name else None
        schedule.save(update_fields=["department"])


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0008_enforce_nullable_optional_session_times"),
    ]

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.RenameField(
            model_name="attendanceschedule",
            old_name="department",
            new_name="legacy_department",
        ),
        migrations.RenameField(
            model_name="attendancesession",
            old_name="department",
            new_name="legacy_department",
        ),
        migrations.AddField(
            model_name="attendanceschedule",
            name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="schedules", to="attendance.department"),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sessions", to="attendance.department"),
        ),
        migrations.RunPython(seed_departments_and_migrate_refs, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="attendanceschedule",
            name="legacy_department",
        ),
        migrations.RemoveField(
            model_name="attendancesession",
            name="legacy_department",
        ),
    ]

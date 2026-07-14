from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0009_department_management"),
    ]

    operations = [
        migrations.CreateModel(
            name="Program",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("code", models.CharField(max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="programs", to="attendance.department")),
            ],
            options={
                "ordering": ("department__name", "code", "name"),
            },
        ),
        migrations.CreateModel(
            name="Section",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("program", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sections", to="attendance.program")),
            ],
            options={
                "ordering": ("program__code", "name"),
            },
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.UniqueConstraint(fields=("department", "name"), name="unique_program_name_per_department"),
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.UniqueConstraint(fields=("department", "code"), name="unique_program_code_per_department"),
        ),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.UniqueConstraint(fields=("program", "name"), name="unique_section_name_per_program"),
        ),
    ]

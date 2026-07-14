from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0010_program_section_models"),
        ("users", "0005_user_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="program",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="attendance.program"),
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=[("admin", "Admin"), ("faculty", "Faculty"), ("student", "Student")], default="faculty", max_length=20),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(condition=~models.Q(school_id=""), fields=("school_id",), name="unique_non_empty_user_school_id"),
        ),
    ]

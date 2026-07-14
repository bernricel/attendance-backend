from django.db import migrations, models
from django.db.models import Count
import django.db.models.deletion


def clear_duplicate_school_ids(apps, schema_editor):
    """
    Existing hosted data may contain duplicate non-empty school IDs.
    Keep the earliest user value and clear later duplicates before adding
    the partial unique constraint.
    """
    User = apps.get_model("users", "User")
    duplicates = (
        User.objects.exclude(school_id="")
        .values("school_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    for duplicate in duplicates:
        school_id = duplicate["school_id"]
        users = list(User.objects.filter(school_id=school_id).order_by("id").values_list("id", flat=True))
        for user_id in users[1:]:
            User.objects.filter(id=user_id).update(school_id="", is_profile_complete=False)


def noop_reverse(apps, schema_editor):
    return None


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
        migrations.RunPython(clear_duplicate_school_ids, noop_reverse),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(condition=~models.Q(school_id=""), fields=("school_id",), name="unique_non_empty_user_school_id"),
        ),
    ]

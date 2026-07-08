from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0009_department_management"),
        ("users", "0004_user_login_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="attendance.department"),
        ),
    ]

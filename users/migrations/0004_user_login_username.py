from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_remove_user_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="login_username",
            field=models.CharField(blank=True, max_length=150, null=True, unique=True),
        ),
    ]

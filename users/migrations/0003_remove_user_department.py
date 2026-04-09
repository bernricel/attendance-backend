from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_remove_user_full_name_alter_user_first_name_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="department",
        ),
    ]

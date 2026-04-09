from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0002_attendancesession_qr_rotation_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="attendancesession",
            name="department",
        ),
        migrations.DeleteModel(
            name="Department",
        ),
    ]

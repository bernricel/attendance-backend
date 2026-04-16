from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0006_session_window_toggles_and_end_time"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendancesession",
            name="late_threshold_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

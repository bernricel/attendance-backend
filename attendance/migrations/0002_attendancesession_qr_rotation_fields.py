from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancesession",
            name="qr_refresh_interval_seconds",
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.AddField(
            model_name="attendancesession",
            name="qr_token_last_rotated_at",
            field=models.DateTimeField(default=timezone.now),
        ),
    ]

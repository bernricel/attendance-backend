from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0011_attendancerecord_section_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancerecord",
            name="is_manual",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="manually_recorded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="manual_attendance_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

from django.db import migrations


def ensure_user_program_column(apps, schema_editor):
    """
    Repair hosted databases where migration history advanced but the physical
    users_user.program_id column was never created.
    """
    User = apps.get_model("users", "User")
    table_name = User._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }

    if "program_id" in existing_columns:
        return

    schema_editor.add_field(User, User._meta.get_field("program"))


def noop_reverse(apps, schema_editor):
    # Never remove production data during rollback.
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0007_alter_user_options"),
    ]

    operations = [
        migrations.RunPython(ensure_user_program_column, noop_reverse),
    ]

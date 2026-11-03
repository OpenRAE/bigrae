"""Retain accepted preparation and prohibit changing its range or executable identity."""

from django.db import migrations, models


def install_guard(apps, schema_editor):
    """Enforce lifetime custody through SQL, including bulk updates."""
    vendor = schema_editor.connection.vendor
    comparison = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    fields = ("preparation", "pin", "pin_digest", "range_id", "installation_id")
    changed = " OR ".join(f"NEW.{name} {comparison} OLD.{name}" for name in fields)
    condition = f"OLD.preparation IS NOT NULL AND ({changed})"
    if vendor == "postgresql":
        schema_editor.execute(f"""CREATE FUNCTION engine_guard_runtime_preparation()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN
                RAISE EXCEPTION 'runtime preparation is immutable' USING ERRCODE = '23514';
            END IF; RETURN NEW; END; $$""")
        schema_editor.execute("""CREATE TRIGGER engine_runtime_preparation_immutable
            BEFORE UPDATE ON engine_runtimepluginrangebinding
            FOR EACH ROW EXECUTE FUNCTION engine_guard_runtime_preparation()""")
    elif vendor == "sqlite":
        schema_editor.execute(f"""CREATE TRIGGER engine_runtime_preparation_immutable
            BEFORE UPDATE ON engine_runtimepluginrangebinding WHEN {condition}
            BEGIN SELECT RAISE(ABORT, 'runtime preparation is immutable'); END""")
    else:
        raise RuntimeError("Unsupported runtime preparation persistence backend")


def remove_guard(apps, schema_editor):
    """Remove only this migration's invariant before reversing the new column."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "DROP TRIGGER IF EXISTS engine_runtime_preparation_immutable ON engine_runtimepluginrangebinding"
        )
        schema_editor.execute("DROP FUNCTION IF EXISTS engine_guard_runtime_preparation()")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS engine_runtime_preparation_immutable")


class Migration(migrations.Migration):
    dependencies = [("engine", "0118_remove_rangeauthoritychange_range_change_operation_and_more")]
    operations = [
        migrations.AddField(
            model_name="runtimepluginrangebinding",
            name="preparation",
            field=models.JSONField(editable=False, null=True),
        ),
        migrations.RunPython(install_guard, remove_guard),
    ]

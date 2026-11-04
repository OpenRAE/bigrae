"""Protect disposable worker custody and single-use trial binding through bulk writes."""

from django.db import migrations


def _guards(vendor):
    """Declare exact retained columns without affecting other range lifecycles."""
    compare = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    worker_fields = (
        "id",
        "range_id",
        "request_id",
        "experiment_id",
        "profile",
        "profile_digest",
        "capacity_scope_ref",
        "deadline",
        "max_recovery_attempts",
        "hold_review_seconds",
        "created_at",
    )
    scope_fields = ("owner_principal_uuid", "scope_kind", "account_id", "organization_id", "workspace_id")
    worker = " OR ".join(f"NEW.{name} {compare} OLD.{name}" for name in worker_fields)
    worker += f" OR (OLD.trial_id IS NOT NULL AND NEW.trial_id {compare} OLD.trial_id)"
    runtime = " OR ".join(
        f"NEW.{name} {compare} OLD.{name}"
        for name in (
            *scope_fields,
            "uuid",
            "request_id",
            "cms_range_uuid",
            "range_config",
            "range_backend",
            "instantiation_purpose",
            "placement_zone",
            "egress_mode",
        )
    )
    request = " OR ".join(f"NEW.{name} {compare} OLD.{name}" for name in (*scope_fields, "request_id"))
    return (
        ("worker_custody", "engine_disposableworker", worker),
        (
            "worker_runtime_custody",
            "mission_control_range",
            f"EXISTS (SELECT 1 FROM engine_disposableworker w WHERE w.range_id = OLD.id) AND ({runtime})",
        ),
        (
            "worker_request_custody",
            "engine_request",
            f"EXISTS (SELECT 1 FROM engine_disposableworker w WHERE w.request_id = OLD.request_id) AND ({request})",
        ),
    )


def install_guards(apps, schema_editor):
    """Use the native database guard convention on PostgreSQL and SQLite."""
    vendor = schema_editor.connection.vendor
    for name, table, condition in _guards(vendor):
        if vendor == "postgresql":
            schema_editor.execute(f"""CREATE FUNCTION engine_guard_{name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF {condition} THEN
                    RAISE EXCEPTION 'worker custody is immutable' USING ERRCODE = '23514';
                END IF; RETURN NEW; END; $$""")
            schema_editor.execute(f"""CREATE TRIGGER engine_{name}_immutable BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION engine_guard_{name}()""")
        elif vendor == "sqlite":
            schema_editor.execute(f"""CREATE TRIGGER engine_{name}_immutable BEFORE UPDATE ON {table}
                WHEN {condition} BEGIN SELECT RAISE(ABORT, 'worker custody is immutable'); END""")
        else:
            raise RuntimeError("Unsupported worker custody persistence backend")
    if vendor == "postgresql":
        schema_editor.execute("""CREATE FUNCTION engine_guard_worker_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'worker custody cannot be deleted' USING ERRCODE = '23514'; END; $$""")
        schema_editor.execute("""CREATE TRIGGER engine_worker_delete_guard BEFORE DELETE ON engine_disposableworker
            FOR EACH ROW EXECUTE FUNCTION engine_guard_worker_delete()""")
    else:
        schema_editor.execute("""CREATE TRIGGER engine_worker_delete_guard BEFORE DELETE ON engine_disposableworker
            BEGIN SELECT RAISE(ABORT, 'worker custody cannot be deleted'); END""")


def remove_guards(apps, schema_editor):
    """Remove only the guards owned by this migration."""
    vendor = schema_editor.connection.vendor
    for name, table, _condition in _guards(vendor):
        suffix = f" ON {table}" if vendor == "postgresql" else ""
        schema_editor.execute(f"DROP TRIGGER IF EXISTS engine_{name}_immutable{suffix}")
        if vendor == "postgresql":
            schema_editor.execute(f"DROP FUNCTION IF EXISTS engine_guard_{name}()")
    suffix = " ON engine_disposableworker" if vendor == "postgresql" else ""
    schema_editor.execute(f"DROP TRIGGER IF EXISTS engine_worker_delete_guard{suffix}")
    if vendor == "postgresql":
        schema_editor.execute("DROP FUNCTION IF EXISTS engine_guard_worker_delete()")


class Migration(migrations.Migration):
    dependencies = [("engine", "0120_disposable_workers")]
    operations = [migrations.RunPython(install_guards, remove_guards)]

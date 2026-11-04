"""Protect scientific custody even through queryset updates and bulk SQL."""

from django.db import migrations

_BATCH = ("id", "organization_uuid", "plan_id", "retained_json", "retained_digest", "concurrency", "created_at")
_ENTRY = ("id", "batch_id", "organization_uuid", "plan_entry_id", "run_id")


def install(apps, editor):
    vendor = editor.connection.vendor
    if vendor not in {"postgresql", "sqlite"}:
        raise RuntimeError("Unsupported experiment persistence backend")
    compare = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    for table, fields in (("cms_experimentbatch", _BATCH), ("cms_experimententry", _ENTRY)):
        changes = [f"NEW.{field} {compare} OLD.{field}" for field in fields]
        if table == "cms_experimententry":
            changes.extend([
                f"OLD.token IS NOT NULL AND NEW.token {compare} OLD.token",
                f"OLD.worker_ref <> '' AND NEW.worker_ref {compare} OLD.worker_ref",
                f"OLD.receipt_id IS NOT NULL AND NEW.receipt_id {compare} OLD.receipt_id",
                f"OLD.cleanup_receipt_json <> '' AND NEW.cleanup_receipt_json {compare} OLD.cleanup_receipt_json",
            ])
        condition = " OR ".join(f"({change})" for change in changes)
        if vendor == "postgresql":
            editor.execute(f"""CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF {condition} THEN RAISE EXCEPTION 'experiment inputs are immutable' USING ERRCODE = '23514';
                END IF; RETURN NEW; END; $$""")
            editor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
                           f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()")
        else:
            editor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} WHEN {condition} "
                           "BEGIN SELECT RAISE(ABORT, 'experiment inputs are immutable'); END")


def remove(apps, editor):
    for table in ("cms_experimententry", "cms_experimentbatch"):
        suffix = f" ON {table}" if editor.connection.vendor == "postgresql" else ""
        editor.execute(f"DROP TRIGGER IF EXISTS {table}_immutable{suffix}")
        if editor.connection.vendor == "postgresql":
            editor.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")


class Migration(migrations.Migration):
    dependencies = [("cms", "0075_experiment_admission")]
    operations = [migrations.RunPython(install, remove)]

"""Retain creation intent independently of later single-use trial binding."""

from django.db import migrations, models


def backfill_initial_trial(apps, schema_editor):
    """Recover later binding from its strict audit without rewriting history."""
    alias = schema_editor.connection.alias
    worker_model = apps.get_model("engine", "DisposableWorker")
    audit_model = apps.get_model("shared", "AuditLog")
    for worker in worker_model.objects.using(alias).exclude(trial_id__isnull=True).iterator():
        bound_later = (
            audit_model.objects.using(alias)
            .filter(entity_type="range", entity_ref=str(worker.pk), new_state__worker_action="worker_trial_bind")
            .exists()
        )
        if not bound_later:
            worker_model.objects.using(alias).filter(pk=worker.pk).update(initial_trial_id=worker.trial_id)


def install_guard(apps, schema_editor):
    """Capture legacy PostgreSQL inserts during rollout and freeze original intent."""
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute("""CREATE FUNCTION engine_guard_worker_initial_trial() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.initial_trial_id IS NOT NULL
                    AND NEW.initial_trial_id IS DISTINCT FROM NEW.trial_id THEN
                    RAISE EXCEPTION 'worker creation intent conflicts' USING ERRCODE = '23514';
                END IF;
                NEW.initial_trial_id := NEW.trial_id;
            ELSIF NEW.initial_trial_id IS DISTINCT FROM OLD.initial_trial_id THEN
                RAISE EXCEPTION 'worker creation intent is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW; END; $$""")
        schema_editor.execute("""CREATE TRIGGER engine_worker_initial_trial_guard
            BEFORE INSERT OR UPDATE ON engine_disposableworker
            FOR EACH ROW EXECUTE FUNCTION engine_guard_worker_initial_trial()""")
    elif vendor == "sqlite":
        schema_editor.execute("""CREATE TRIGGER engine_worker_initial_trial_insert_guard
            BEFORE INSERT ON engine_disposableworker WHEN NEW.initial_trial_id IS NOT NEW.trial_id
            BEGIN SELECT RAISE(ABORT, 'worker creation intent conflicts'); END""")
        schema_editor.execute("""CREATE TRIGGER engine_worker_initial_trial_guard
            BEFORE UPDATE ON engine_disposableworker WHEN NEW.initial_trial_id IS NOT OLD.initial_trial_id
            BEGIN SELECT RAISE(ABORT, 'worker creation intent is immutable'); END""")
    else:
        raise RuntimeError("Unsupported worker custody persistence backend")


def remove_guard(apps, schema_editor):
    """Remove only this migration's creation-intent guards."""
    vendor = schema_editor.connection.vendor
    suffix = " ON engine_disposableworker" if vendor == "postgresql" else ""
    for name in ("engine_worker_initial_trial_guard", "engine_worker_initial_trial_insert_guard"):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}{suffix}")
    if vendor == "postgresql":
        schema_editor.execute("DROP FUNCTION IF EXISTS engine_guard_worker_initial_trial()")


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0123_worker_host_observations"),
        ("shared", "0032_capacity_assessment_audit_entity"),
    ]
    operations = [
        migrations.AddField(
            model_name="disposableworker",
            name="initial_trial_id",
            field=models.UUIDField(
                blank=True,
                editable=False,
                help_text="Trial requested at creation, before any later binding",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_initial_trial, migrations.RunPython.noop),
        migrations.RunPython(install_guard, remove_guard),
    ]

"""Retire the portal management-reference projection without rewriting results."""

from django.db import migrations, models
from django.db.models.fields.json import KeyTextTransform


def clear_retired_references(apps, schema_editor):
    """Require native cleanup of all previous workers before the boundary cutover."""
    alias = schema_editor.connection.alias
    if apps.get_model("engine", "DisposableWorker").objects.using(alias).filter(terminal_at__isnull=True).exists():
        raise RuntimeError("Retire existing disposable workers before upgrading host observations")
    apps.get_model("engine", "RangeManagementAccess").objects.using(alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [("engine", "0122_merge_worker_and_cloud_custody")]
    operations = [
        migrations.RunPython(clear_retired_references, migrations.RunPython.noop),
        migrations.RenameModel("RangeManagementAccess", "WorkerHostObservation"),
        migrations.RenameField("WorkerHostObservation", "bindings", "observations"),
        migrations.AddConstraint(
            model_name="disposableworker",
            constraint=models.UniqueConstraint(
                KeyTextTransform("vm_identity", "qualification"),
                condition=models.Q(qualification__has_key="vm_identity"),
                name="worker_independent_vm",
            ),
        ),
    ]

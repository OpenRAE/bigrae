from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0079_experiment_entry_replacement"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="experimententry", name="experiment_entry_replacement_shape"),
        migrations.RemoveConstraint(model_name="experimententry", name="experiment_tenant_entry_unique"),
        migrations.RemoveConstraint(model_name="experimententry", name="experiment_tenant_run_unique"),
        migrations.RemoveField(model_name="experimententry", name="replacement_json"),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.UniqueConstraint(
                condition=models.Q(replacement_ordinal__isnull=True),
                fields=("organization_uuid", "plan_entry_id"),
                name="experiment_tenant_entry_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.UniqueConstraint(
                condition=models.Q(replacement_ordinal__isnull=True),
                fields=("organization_uuid", "run_id"),
                name="experiment_tenant_run_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.UniqueConstraint(
                fields=("organization_uuid", "plan_entry_id", "replacement_ordinal"),
                name="experiment_tenant_entry_rerun_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(replaces__isnull=True, replacement_ordinal__isnull=True),
                    models.Q(replaces__isnull=False, replacement_ordinal__gte=1),
                    _connector="OR",
                ),
                name="experiment_entry_replacement_shape",
            ),
        ),
    ]

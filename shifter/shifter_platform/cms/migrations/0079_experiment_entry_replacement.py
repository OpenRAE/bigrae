import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0078_experiment_dispatch_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="experimententry",
            name="replaces",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="replacements",
                to="cms.experimententry",
            ),
        ),
        migrations.AddField(
            model_name="experimententry",
            name="replacement_ordinal",
            field=models.PositiveSmallIntegerField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="experimententry",
            name="replacement_json",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.UniqueConstraint(fields=("replaces",), name="experiment_entry_replaced_once"),
        ),
        migrations.AddConstraint(
            model_name="experimententry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(replaces__isnull=True, replacement_ordinal__isnull=True, replacement_json=""),
                    models.Q(replaces__isnull=False, replacement_ordinal__gte=1),
                    _connector="OR",
                ),
                name="experiment_entry_replacement_shape",
            ),
        ),
    ]

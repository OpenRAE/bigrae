from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0120_registered_gcp_range_projects")]
    operations = [
        migrations.AddField(
            model_name="range", name="raes_cloud_content", field=models.JSONField(editable=False, null=True)
        )
    ]

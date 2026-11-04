"""Join independently delivered worker and registered-project migration branches."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0121_worker_custody_guards"),
        ("engine", "0121_raes_cloud_content"),
    ]
    operations = []

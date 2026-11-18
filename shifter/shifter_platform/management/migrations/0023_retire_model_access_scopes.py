"""Disable service admissions that hold a scope retired with the model broker (#2909)."""

from django.db import migrations

from shared.retired_authorization import holds_retired


def scrub(apps, schema_editor):
    """Admission scopes are immutable, so an admission with a retired scope is disabled."""
    admission = apps.get_model("management", "ServiceCredentialAdmission")
    retired = [
        row.pk
        for row in admission._base_manager.filter(is_active=True).only("pk", "scopes").iterator(chunk_size=500)
        if isinstance(row.scopes, list) and holds_retired(row.scopes)
    ]
    if retired:
        admission._base_manager.filter(pk__in=retired).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("management", "0022_remove_model_access")]

    operations = [migrations.RunPython(scrub, migrations.RunPython.noop)]

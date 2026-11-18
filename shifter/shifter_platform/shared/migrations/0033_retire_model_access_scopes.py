"""Revoke personal credentials that hold a scope retired with the model broker (#2909)."""

from django.db import migrations
from django.utils import timezone

from shared.retired_authorization import holds_retired


def scrub(apps, schema_editor):
    """Credential scopes are immutable, so a token with a retired scope is revoked for reissue."""
    token = apps.get_model("shared", "ApiToken")
    retired = [
        row.pk
        for row in token._base_manager.filter(revoked_at__isnull=True).only("pk", "scopes").iterator(chunk_size=500)
        if isinstance(row.scopes, list) and holds_retired(row.scopes)
    ]
    if retired:
        token._base_manager.filter(pk__in=retired, revoked_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("shared", "0032_capacity_assessment_audit_entity")]

    operations = [migrations.RunPython(scrub, migrations.RunPython.noop)]

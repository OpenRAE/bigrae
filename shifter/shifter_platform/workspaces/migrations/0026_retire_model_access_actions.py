"""Delete authorization journal rows for actions retired with the model broker (#2909)."""

from django.db import migrations

from shared.retired_authorization import RETIRED_ACTIONS


def scrub(apps, schema_editor):
    """A retired action can no longer be reconstructed, replayed, or reconciled."""
    operation = apps.get_model("workspaces", "AuthorizationOperation")
    operation._base_manager.filter(action__in=RETIRED_ACTIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0025_invitation_delivery_status")]

    operations = [migrations.RunPython(scrub, migrations.RunPython.noop)]

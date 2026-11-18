"""Remove model-access values from pending CTF event initialization intents (#2909)."""

from django.db import migrations

from shared.retired_authorization import without_retired


def clean_initialization_intent(intent: dict) -> dict:
    """Drop the model-source selection and retired credential limits from a pending intent."""
    cleaned = {key: value for key, value in intent.items() if key != "model_sources"}
    authority = cleaned.get("authority")
    if isinstance(authority, dict):
        cleaned["authority"] = authority | {
            key: without_retired(authority[key]) for key in ("ceiling_actions", "scopes") if key in authority
        }
    return cleaned


def scrub(apps, schema_editor):
    """Keep a pending event initialization resumable after model access is removed."""
    event = apps.get_model("ctf", "CTFEvent")
    for row in event._base_manager.filter(initialization_intent__isnull=False).only("pk", "initialization_intent"):
        cleaned = clean_initialization_intent(row.initialization_intent)
        if cleaned != row.initialization_intent:
            event._base_manager.filter(pk=row.pk).update(initialization_intent=cleaned)


class Migration(migrations.Migration):
    dependencies = [("ctf", "0089_remove_model_access")]

    operations = [migrations.RunPython(scrub, migrations.RunPython.noop)]

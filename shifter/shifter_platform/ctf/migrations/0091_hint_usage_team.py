"""Record the team on each hint usage so team-mode penalties apply to the whole team."""

import django.db.models.deletion
from django.db import migrations, models


def backfill_team(apps, schema_editor):
    """Attribute existing team-mode unlocks to the participant's current team."""
    usage_model = apps.get_model("ctf", "CTFHintUsage")
    for usage in usage_model.objects.filter(
        team__isnull=True, participant__event__team_mode=True, participant__team__isnull=False
    ).select_related("participant"):
        usage.team_id = usage.participant.team_id
        usage.save(update_fields=["team"])


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0090_retire_model_access_records"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctfhintusage",
            name="team",
            field=models.ForeignKey(
                blank=True,
                help_text="Team of the participant at unlock time; the penalty applies to the whole team",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hint_usages",
                to="ctf.ctfteam",
            ),
        ),
        migrations.RunPython(backfill_team, migrations.RunPython.noop),
    ]

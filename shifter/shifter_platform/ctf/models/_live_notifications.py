"""Model mixin, default, and validator for the event's live notification kinds (CTF-802, ADR-072)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from ctf.enums import LiveNotificationKind


def default_live_notifications() -> list[str]:
    """A new event selects every kind; pre-existing events migrate to none."""
    return [kind.value for kind in LiveNotificationKind]


def validate_live_notifications(value: object) -> None:
    """Accept only a list of distinct, known kinds."""
    allowed = {kind.value for kind in LiveNotificationKind}
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in allowed for item in value):
        raise ValidationError("Select only supported live notification kinds.")
    if len(set(value)) != len(value):
        raise ValidationError("Select each live notification kind once.")


class LiveNotificationsMixin(models.Model):
    """The event's selected live notification kinds (CTF-802, ADR-072)."""

    live_notifications = models.JSONField(
        default=default_live_notifications,
        blank=True,
        validators=[validate_live_notifications],
        help_text="Live notification kinds this event publishes; an empty list publishes nothing (CTF-802)",
    )

    class Meta:
        """Abstract: the field belongs to the concrete event model."""

        abstract = True

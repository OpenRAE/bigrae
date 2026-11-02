"""Real-time in-app notifications over the shared WebSocket bus (CTF-802).

CTF publishes event-scoped browser notifications through
:mod:`shared.notifications` (PLAT-105): one notification type
(``ctf_event``) on per-event topics ``ctf:event:<uuid>``. Subscription is
authorized for the event's viewing participants, staff, and the owning
organizer. Publishing is best-effort — a bus outage never affects the
triggering action — and disconnected participants receive pending
notifications on their next connection (shared-bus replay).

Frames stay in a closed, content-free set (ADR-072-R4): a message reference,
a ``position_changed`` or ``range_ready`` hint, or a generic ``refresh``.
Each hint has its own occurrence identity, so distinct hints never collapse.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from ctf.enums import LiveNotificationKind
from shared.credentials import CredentialContext

if TYPE_CHECKING:
    from ctf.models import CTFEvent

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "ctf_event"
TOPIC_PREFIX = "ctf:event"

# Content-free socket hints; the browser reads detail only through authenticated APIs.
HINT_KINDS = frozenset({LiveNotificationKind.POSITION_CHANGED, LiveNotificationKind.RANGE_READY})


def event_topic(event_id: object) -> str:
    """Return the per-event notification topic."""
    return f"{TOPIC_PREFIX}:{event_id}"


def _topic_event(topic: str) -> CTFEvent | None:
    """Resolve a ``ctf:event:<uuid>`` topic to a live event, or None."""
    from uuid import UUID

    from ctf.models import CTFEvent

    try:
        event_id = UUID(topic.rsplit(":", 1)[-1])
    except ValueError:
        return None
    return CTFEvent.objects.filter(pk=event_id, deleted_at__isnull=True).only("id", "created_by_id").first()


def _can_subscribe(credential: CredentialContext, topic: str) -> bool:
    """Authorize the actual current browser proof, never SQL owner/group flags."""
    from ctf.exceptions import CTFError
    from ctf.services.event_projection import authorize_event_projection

    if not isinstance(credential, CredentialContext) or credential.principal.kind != "human":
        return False
    event = _topic_event(topic)
    if event is None:
        return False
    try:
        authorize_event_projection(credential, event.pk)
        allowed = True
    except CTFError:
        allowed = False
    return allowed


def _reference_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    """Never replay retained legacy content through the newly admitted socket."""
    kind = payload.get("kind")
    if kind in {hint.value for hint in HINT_KINDS}:
        return {"kind": kind}
    return _communication_reference(payload) if kind == "communication" else {"kind": "refresh"}


def _communication_reference(payload: Mapping[str, Any]) -> dict[str, str]:
    """Project a message wake-up to its validated identifiers, or a refresh hint."""
    try:
        return {
            "kind": "communication",
            "snapshot_id": str(UUID(payload["snapshot_id"])),
            "intent_id": str(UUID(payload["intent_id"])),
        }
    except (KeyError, ValueError, TypeError, AttributeError):
        return {"kind": "refresh"}


def register_ctf_notifications() -> None:
    """Register the CTF notification type with the shared bus (idempotent)."""
    from shared.notifications import register_notification_type

    register_notification_type(
        name=NOTIFICATION_TYPE,
        topic_prefix=TOPIC_PREFIX,
        can_subscribe=_can_subscribe,
        payload_handler=_reference_payload,
    )


def publish_live_hint(
    event: CTFEvent,
    kind: LiveNotificationKind,
    *,
    recipient_ids: list[int],
    occurrence: str,
) -> int:
    """Publish one content-free hint to ``recipient_ids``, best-effort (CTF-802).

    ``occurrence`` names this hint (for example, a range generation or one
    reconcile result), so a replay maps to the same row and distinct hints never
    collapse onto the event's identity. Returns the number of rows published; 0
    when the event does not select ``kind`` or there is no account recipient.
    """
    from ctf.services.notification.live import live_kind_enabled
    from shared.notifications import publish_notification

    kind = LiveNotificationKind(kind)
    if kind not in HINT_KINDS:
        raise ValueError("Unsupported live hint")
    recipients = [int(user_id) for user_id in recipient_ids if user_id is not None]
    if not recipients or not live_kind_enabled(event, kind):
        return 0
    published: list[Any] = []
    try:
        # Idempotent re-registration: registration normally happens in
        # apps.ready, but a registry reset must not silently drop the hint.
        register_ctf_notifications()
        published = publish_notification(
            NOTIFICATION_TYPE,
            topic=event_topic(event.pk),
            payload={"kind": kind.value},
            recipient_ids=recipients,
            event_id=uuid5(NAMESPACE_URL, f"shifter:ctf-live-hint:{event.pk}:{kind.value}:{occurrence}"),
        )
    except Exception:
        logger.exception("Failed to publish %s hint for event %s", kind.value, event.pk)
    return len(published)


def publish_communication_wakeup(
    *,
    event_id: UUID | str,
    recipient_user_id: int,
    snapshot_id: UUID | str,
    references: dict[str, str],
) -> bool:
    """Publish one reference-only in-app communication wake-up, best-effort (#2098).

    The wake-up is an accelerator over the durable inbox (the ``RecipientSnapshot`` /
    ``RecipientReceipt`` committed at admission), never the source of truth. It
    uses the stable per-recipient ``snapshot_id`` as the shared replay identity so
    distinct communications never collapse onto one row and a replayed wake-up maps
    to the same row (no duplicate visible entries). It carries only
    identifiers, never message subject, body, recipient PII, or secrets.

    Returns True when a wake-up row was published, False when the subsystem is
    disabled or there is no account recipient to wake.
    """
    from shared.notifications import notifications_enabled, publish_notification

    if not notifications_enabled() or recipient_user_id is None:
        return False
    # Idempotent re-registration (mirrors publish_live_hint): a registry
    # reset or test isolation must not silently drop the wake-up.
    register_ctf_notifications()
    published = publish_notification(
        NOTIFICATION_TYPE,
        topic=event_topic(event_id),
        payload={"kind": "communication", **references},
        recipient_ids=[int(recipient_user_id)],
        event_id=snapshot_id,
    )
    return bool(published)

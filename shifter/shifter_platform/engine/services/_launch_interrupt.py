"""Durable interrupt requests for a provision-task generation (#277).

Callers record an interrupt under their own transaction. The launcher worker
converges the recorded request in ``_launch_interrupt_convergence``.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from engine.models import InterruptState, ProvisionerLaunchIntent, Range

# Bounded convergence budget for a provision-task interrupt (#277). Safe internal
# default; promote to a typed deployment setting only if operators need to tune it.
_INTERRUPT_DEADLINE_SECONDS = 1800
# Only the RAES provision generation is interruptible in this scope (#277); the
# AWS legacy ``range`` provision path is #1894.
_INTERRUPTIBLE_PROVISION = ("raes-range", "provision")


def request_provision_interrupt(range_obj: Range) -> bool:
    """Record a durable interrupt against the range's current provision generation (#277).

    Bound under the caller's transaction to the current ``provisioner_operation_id``
    -- never keyed by ``request_id`` or task reference alone. Scoped to the RAES
    provision path; the AWS legacy ``range`` path is out of scope (#1894). The
    launcher worker converges the recorded request (suppress pending / stop running
    / observe terminal absence / enqueue canonical destroy). Idempotent: returns
    True without re-stamping when the generation is already marked.

    Returns:
        True when an interruptible provision generation was (or already is) marked.
    """
    intent = _interruptible_provision_intent(range_obj)
    if intent is None:
        return False
    _request_intent_interrupt(intent)
    return True


def _request_intent_interrupt(intent: ProvisionerLaunchIntent) -> None:
    """Suppress one validated native generation before observing provider absence."""
    if intent.interrupt_state != InterruptState.NONE:
        return
    now = timezone.now()
    intent.interrupt_state = InterruptState.REQUESTED
    intent.interrupt_requested_at = now
    intent.interrupt_next_attempt_at = now
    intent.interrupt_deadline = now + timedelta(seconds=_INTERRUPT_DEADLINE_SECONDS)
    intent.save(
        update_fields=[
            "interrupt_state",
            "interrupt_requested_at",
            "interrupt_next_attempt_at",
            "interrupt_deadline",
        ]
    )


def _interruptible_provision_intent(range_obj: Range) -> ProvisionerLaunchIntent | None:
    """Return the range's current launch intent when its generation can be interrupted.

    ``None`` when the range has no reserved generation, no intent is recorded for
    it, or the recorded intent is not the RAES provision operation the interrupt
    path converges.
    """
    op_id = range_obj.provisioner_operation_id
    intent = (
        ProvisionerLaunchIntent.objects.select_for_update().filter(operation_id=op_id).first()
        if op_id is not None
        else None
    )
    if intent is None:
        return None
    payload = intent.payload or {}
    if payload.get("resource") != "raes-range" or payload.get("operation") not in {"provision", "activate"}:
        return None
    return intent

"""Containment and verified retirement retain uncertain native call exclusion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from ._cleanup_verification import is_range_generation_cleanup_verified_absent
from ._native_participant_invocation import native_participant_power_unresolved

if TYPE_CHECKING:
    from engine.models import Range
    from shared.native_participant import NativeRuntimeCoordinates


def fence_native_power_for_teardown(row: Range) -> int:
    """The owning authorized teardown transaction excludes all later power grants."""
    from engine.models import ParticipantPowerReservation

    if not transaction.get_connection().in_atomic_block:
        raise ValueError("Native teardown fence requires its owning transaction")
    return ParticipantPowerReservation.objects.filter(
        compiler_binding__range=row,
        fenced_at__isnull=True,
    ).update(fenced_at=timezone.now())


def native_participant_power_requires_exclusion(coordinates: NativeRuntimeCoordinates) -> bool:
    """Close an old owner after verified world retirement without claiming call cessation."""
    from engine.models import Range

    if not native_participant_power_unresolved(coordinates):
        return False
    row = Range.objects.select_related("request").get(
        compiler_input_bindings__binding_ref=coordinates.binding_ref,
        resource_generation=coordinates.resource_generation,
    )
    return not (
        row.request is not None
        and row.cms_range_uuid is not None
        and is_range_generation_cleanup_verified_absent(row.request.request_id, row.cms_range_uuid, row.pk)
    )

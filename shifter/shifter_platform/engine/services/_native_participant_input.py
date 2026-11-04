"""Private installation input through current compiler and native custody."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.credentials import resolve_local_credential
from shared.exceptions import ValidationError
from shared.native_participant import NativeRuntimeCoordinates
from shared.operation_envelope import canonical_payload_digest
from shared.raes.power_input import NativePowerInput, build_native_power_input, parse_native_power_input

from ._common import EngineError
from ._compiled_participants import BoundCompilerInput, _read_current_compiler_input, _scope_digest
from ._range_authority import require_native_range_action

if TYPE_CHECKING:
    from engine.models import Range
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext

_UNAVAILABLE = "Native participant installation input unavailable"


@dataclass(frozen=True, slots=True)
class BoundNativeParticipantInput:
    """Private installation facts; neither status projection nor effect permit."""

    compiler: BoundCompilerInput
    power: NativePowerInput = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedNativeParticipantInput:
    """Invocation-local admission; fence it inside the owning product transaction."""

    input: BoundNativeParticipantInput = field(repr=False)
    _credential: CredentialContext = field(repr=False)
    _range_pk: int
    _installation_digest: str = field(repr=False)


def _installation_digest(row: Range) -> str:
    return canonical_payload_digest(
        {
            "custody": _scope_digest(row),
            "generation": str(row.resource_generation),
            "status": row.status,
            "backend": row.range_backend,
            "firewall": row.ngfw_instance_id,
            "members": row.provisioned_instances,
        }
    )


def read_range_participant_power_input(
    credential: CredentialContext,
    request_id: UUID,
    *,
    authority_target: TargetRef | None = None,
) -> BoundNativeParticipantInput:
    """Authorize before locks and decryption; qualify the exact retained footprint."""
    return prepare_range_participant_power_input(credential, request_id, authority_target=authority_target).input


def prepare_range_participant_power_input(
    credential: CredentialContext,
    request_id: UUID,
    *,
    authority_target: TargetRef | None = None,
) -> PreparedNativeParticipantInput:
    """Evaluate remote authority before the caller acquires product/CMS locks."""
    return _prepare_input(credential, request_id, authority_target=authority_target)


def prepare_bound_range_participant_power_input(
    credential: CredentialContext,
    request_id: UUID,
    coordinates: NativeRuntimeCoordinates,
    *,
    authority_target: TargetRef | None = None,
) -> PreparedNativeParticipantInput:
    """Recover only an already bound generation; pending state grants no new effect."""
    if not isinstance(coordinates, NativeRuntimeCoordinates):
        raise EngineError(_UNAVAILABLE)
    return _prepare_input(credential, request_id, authority_target=authority_target, coordinates=coordinates)


def _prepare_input(
    credential: CredentialContext,
    request_id: UUID,
    *,
    authority_target: TargetRef | None,
    coordinates: NativeRuntimeCoordinates | None = None,
) -> PreparedNativeParticipantInput:
    from engine.models import Range

    baseline = require_native_range_action(
        credential,
        request_id,
        "event.manage_ranges" if authority_target is not None else "range.manage",
        authority_target=authority_target,
    )
    expected = _installation_digest(baseline)
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=baseline.pk)
        if (
            _installation_digest(row) != expected
            or resolve_local_credential(credential) != credential
            or row.status
            not in ({"ready", "paused", "pausing", "resuming", "failed"} if coordinates else {"ready", "paused"})
            or row.ngfw_instance_id is not None
        ):
            raise EngineError(_UNAVAILABLE)
        if coordinates is not None:
            from engine.models import RaesCompilerInputBinding

            if (
                row.resource_generation != coordinates.resource_generation
                or not RaesCompilerInputBinding.objects.filter(
                    range=row,
                    binding_ref=coordinates.binding_ref,
                    resource_generation=row.resource_generation,
                    scope_digest=_scope_digest(row),
                ).exists()
            ):
                raise EngineError(_UNAVAILABLE)
        try:
            power = parse_native_power_input(
                build_native_power_input(
                    row.range_config,
                    row.provisioned_instances,
                    row.resource_generation,
                    backend=str(row.range_backend or ""),
                ),
                plan=row.range_config,
            )
        except ValidationError:
            raise EngineError(_UNAVAILABLE) from None
        from ._native_participant_origin import native_power_origin

        native_power_origin(row)
        return PreparedNativeParticipantInput(
            BoundNativeParticipantInput(_read_current_compiler_input(row), power), credential, row.pk, expected
        )


def fence_range_participant_power_input(prepared: PreparedNativeParticipantInput) -> BoundNativeParticipantInput:
    """Hold unchanged native generation, scope, footprint and proof through commit."""
    from engine.models import Range

    if not transaction.get_connection().in_atomic_block:
        raise EngineError("Native installation fence requires a transaction")
    try:
        row = Range.objects.select_for_update().get(pk=prepared._range_pk)
        if (
            _installation_digest(row) != prepared._installation_digest
            or resolve_local_credential(prepared._credential) != prepared._credential
            or _read_current_compiler_input(row) != prepared.input.compiler
        ):
            raise EngineError(_UNAVAILABLE)
        return prepared.input
    except Exception:  # noqa: BLE001  # native admission details remain private
        raise EngineError(_UNAVAILABLE) from None

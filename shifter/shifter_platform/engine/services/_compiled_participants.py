"""Persist compiler references without confusing them with control authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from shared.operation_envelope import MAX_ENVELOPE_BYTES, canonical_payload_digest
from shared.raes.compiled_participants import (
    MAX_PARAMETER_BYTES,
    CompiledParticipantContext,
    CompiledParticipantReferences,
)

from ._common import EngineError

if TYPE_CHECKING:
    from engine.models import Range
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext


@dataclass(frozen=True, slots=True)
class BoundCompilerInput:
    """Private worker input, never an HTTP or portable evidence projection."""

    binding_ref: UUID
    resource_generation: UUID
    source_package_digest: str
    context: CompiledParticipantContext = field(repr=False)


def _scope_digest(row: Range) -> str:
    """Custody, source request and incarnation are independent binding dimensions."""
    compiled_plan = row.range_config
    if not isinstance(compiled_plan, dict):
        raise EngineError("Range compiler input is unavailable")
    return canonical_payload_digest(
        {
            "request_pk": row.request_id,
            "owner_principal_uuid": str(row.owner_principal_uuid) if row.owner_principal_uuid is not None else None,
            "user_id": row.user_id,
            "cms_user_id": row.cms_user_id,
            "public_uuid": str(row.cms_range_uuid) if row.cms_range_uuid is not None else None,
            "event_uuid": str(row.event_uuid) if row.event_uuid is not None else None,
            "scope_kind": row.scope_kind,
            "account_id": row.account_id,
            "organization_id": row.organization_id,
            "workspace_id": row.workspace_id,
            "compiled_plan_digest": canonical_payload_digest(compiled_plan),
        }
    )


def read_range_compiler_input(
    credential: CredentialContext,
    request_id: UUID,
    *,
    authority_target: TargetRef | None = None,
) -> BoundCompilerInput:
    """Authorize before decrypting input for the admitted native runtime worker."""
    from django.db import transaction

    from engine.models import Range

    from ._range_authority import require_native_range_action

    row = require_native_range_action(
        credential,
        request_id,
        "event.manage_ranges" if authority_target is not None else "range.manage",
        authority_target=authority_target,
    )
    expected = row.resource_generation, _scope_digest(row)
    with transaction.atomic():
        current = Range.objects.select_for_update().get(pk=row.pk)
        if (current.resource_generation, _scope_digest(current)) != expected:
            raise EngineError("Range compiler input is unavailable")
        return _read_current_compiler_input(current)


def _read_current_compiler_input(row: Range) -> BoundCompilerInput:
    """Keep decryption after authorization and the locked native custody fence."""
    from engine.models import RaesCompilerInputBinding

    if row.resource_generation is None:
        raise EngineError("Range compiler input is unavailable")
    try:
        binding = RaesCompilerInputBinding.objects.filter(
            range=row,
            resource_generation=row.resource_generation,
            scope_digest=_scope_digest(row),
        ).first()
        if binding is None:
            raise EngineError("Range compiler input is unavailable")
        references = tuple(
            CompiledParticipantReferences(
                participant_ref=entry["participant_ref"],
                scope_refs=tuple(entry["scope_refs"]),
                behavior_specification_refs=tuple(entry["behavior_specification_refs"]),
            )
            for entry in binding.participant_references
        )
        context = CompiledParticipantContext(
            raes_version=binding.raes_version,
            compiler_input_digest=binding.compiler_input_digest,
            parameters_json=(binding.parameters_json or "{}").encode("utf-8"),
            participants=references,
            artifact_planning_json=binding.artifact_planning_json.encode("utf-8"),
        )
        return BoundCompilerInput(binding.binding_ref, row.resource_generation, binding.source_package_digest, context)
    except (TypeError, ValueError, KeyError):
        raise EngineError("Range compiler input is unavailable") from None


def persist_compiled_participant_binding(
    row: Range, context: CompiledParticipantContext | None, source_package_digest: str
) -> None:
    """Join encrypted private selections to the range in its existing transaction."""
    from engine.models import RaesCompilerInputBinding

    if context is None:
        return
    if (
        not isinstance(context, CompiledParticipantContext)
        or row.resource_generation is None
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", source_package_digest)
        or len(context.parameters_json) > MAX_PARAMETER_BYTES
        or len(context.artifact_planning_json) > MAX_ENVELOPE_BYTES
    ):
        raise EngineError("Range compiler input is unavailable")
    try:
        parameters = json.loads(context.parameters_json)
        artifact_planning_json = context.artifact_planning_json.decode("utf-8")
    except (TypeError, ValueError):
        raise EngineError("Range compiler input is unavailable") from None
    if not isinstance(parameters, dict):
        raise EngineError("Range compiler input is unavailable")
    private_selection = (
        json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False) if parameters else ""
    )
    RaesCompilerInputBinding.objects.create(
        range=row,
        resource_generation=row.resource_generation,
        scope_digest=_scope_digest(row),
        source_package_digest=source_package_digest,
        compiler_input_digest=context.compiler_input_digest,
        raes_version=context.raes_version,
        parameters_json=private_selection,
        artifact_planning_json=artifact_planning_json,
        participant_references=context.reference_payload(),
    )


def verify_raes_range_compilation(
    request_id: UUID,
    compiled_plan: dict[str, object],
    *,
    context: CompiledParticipantContext | None,
    source_package_digest: str,
) -> None:
    """Check immutable compilation on a separately authorized product replay."""
    from engine.models import Range

    row = Range.objects.get(request__request_id=request_id)
    if row.range_config != compiled_plan:
        raise EngineError("Range plan conflict")
    verify_compiled_participant_binding(row, context, source_package_digest)


def verify_compiled_participant_binding(
    row: Range,
    context: CompiledParticipantContext | None,
    source_package_digest: str,
) -> None:
    """Never replace, omit or silently upgrade a retained generation's input."""
    from engine.models import RaesCompilerInputBinding

    retained = RaesCompilerInputBinding.objects.filter(range=row)
    if context is None:
        if retained.exists():
            raise EngineError("Range compiler input changed")
        return
    if row.resource_generation is None:
        raise EngineError("Range compiler input changed")
    binding = retained.filter(resource_generation=row.resource_generation, scope_digest=_scope_digest(row)).first()
    if binding is None or (
        binding.source_package_digest != source_package_digest
        or binding.compiler_input_digest != context.compiler_input_digest
        or binding.raes_version != context.raes_version
        or binding.participant_references != context.reference_payload()
        or (binding.parameters_json or "{}").encode("utf-8") != context.parameters_json
        or binding.artifact_planning_json.encode("utf-8") != context.artifact_planning_json
    ):
        raise EngineError("Range compiler input changed")


def current_compiled_participant_projection(row: Range) -> dict[str, object] | None:
    """Read references only; neither decrypt parameters nor expose their compiler digest."""
    from engine.models import RaesCompilerInputBinding

    if row.resource_generation is None:
        return None
    binding = (
        RaesCompilerInputBinding.objects.filter(
            range=row, resource_generation=row.resource_generation, scope_digest=_scope_digest(row)
        )
        .only("binding_ref", "resource_generation", "participant_references")
        .first()
    )
    if binding is None:
        return None
    return {
        "binding_ref": str(binding.binding_ref),
        "resource_generation": str(binding.resource_generation),
        "participant_refs": [entry["participant_ref"] for entry in binding.participant_references],
        "reference_only": True,
    }

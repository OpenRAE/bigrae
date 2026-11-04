"""Native, body-free references to retained RAES compiler input.

This is compilation metadata, never participant identity, authority, an active
episode, or a substitute for the released control-plane store.
"""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from raes_contracts.canonical import canonical_json_digest
from raes_processor.compiler import compile_runtime_model, compile_scenario_runtime_model
from raes_processor.models import RuntimeModel

if TYPE_CHECKING:
    from raes.scenarios import Scenario

MAX_PARAMETER_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class CompiledParticipantReferences:
    """Compiler-owned addresses; none of them establishes a native actor mapping."""

    participant_ref: str
    scope_refs: tuple[str, ...]
    behavior_specification_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledParticipantContext:
    """A detached native selection with an explicitly body-free reference view."""

    raes_version: str
    compiler_input_digest: str = field(repr=False)
    parameters_json: bytes = field(repr=False)
    participants: tuple[CompiledParticipantReferences, ...]
    artifact_planning_json: bytes = field(default=b"", repr=False)

    def reference_payload(self) -> list[dict[str, object]]:
        """Return detached references suitable for native binding persistence."""
        return [
            {
                "participant_ref": participant.participant_ref,
                "scope_refs": list(participant.scope_refs),
                "behavior_specification_refs": list(participant.behavior_specification_refs),
            }
            for participant in self.participants
        ]


def project_compiled_participants(
    model: RuntimeModel, *, parameters: Mapping[str, object] | None = None
) -> CompiledParticipantContext | None:
    """Project actual retained input rather than mutable post-compile dictionaries."""
    if not isinstance(model, RuntimeModel) or model.realization_instance is None:
        raise ValueError("Retained compiler input is unavailable")
    try:
        canonical = compile_runtime_model(model.realization_instance)
        if not canonical.participant_behaviors:
            return None
        values = dict(parameters or {})
        if any(not isinstance(key, str) for key in values):
            raise ValueError("Invalid parameter keys")
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_PARAMETER_BYTES:
            raise ValueError("Parameter selection is too large")
        references = tuple(
            CompiledParticipantReferences(
                participant_ref=participant.address,
                scope_refs=tuple(participant.operating_scope_addresses),
                behavior_specification_refs=tuple(
                    sorted(
                        specification.address
                        for specification in canonical.behavior_specifications.values()
                        if participant.address in specification.participant_addresses
                    )
                ),
            )
            for _, participant in sorted(canonical.participant_behaviors.items())
        )
        return CompiledParticipantContext(
            raes_version=importlib.metadata.version("raes"),
            compiler_input_digest=canonical_json_digest(model.realization_instance.model_dump(mode="json")),
            parameters_json=encoded,
            participants=references,
        )
    except Exception:  # noqa: BLE001  # compiler/serializer diagnostics may contain private source or parameters
        raise ValueError("Retained compiler input is unavailable") from None


def restore_compiled_model(scenario: Scenario, context: CompiledParticipantContext) -> RuntimeModel:
    """Recompile an independently authorized, digest-verified immutable package.

    The native package owner verifies the package pin before supplying its
    scenario. This second check verifies the exact released compiler input,
    retained selections and references; it grants no authority or capability.
    """
    try:
        if context.raes_version != importlib.metadata.version("raes"):
            raise ValueError("Compiler version changed")
        if len(context.parameters_json) > MAX_PARAMETER_BYTES:
            raise ValueError("Parameter selection is too large")
        parameters = json.loads(context.parameters_json)
        if not isinstance(parameters, dict):
            raise ValueError("Parameter selection is invalid")
        model = compile_scenario_runtime_model(scenario, parameters=parameters)
        if project_compiled_participants(model, parameters=parameters) != replace(context, artifact_planning_json=b""):
            raise ValueError("Compiler input changed")
        return model
    except Exception:  # noqa: BLE001  # only authored diagnostics cross this private-input boundary
        raise ValueError("Retained compiler input changed") from None

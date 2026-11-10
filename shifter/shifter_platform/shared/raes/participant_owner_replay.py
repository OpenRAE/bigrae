"""Replay a backend owner's participant configuration results at admission.

The installed adapter runs the owner in its isolated worker (``validate``
phase). The compiler then receives a validator that returns exactly those
normalized configurations and accepts exactly those control-context
selections; any other configuration is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from raes_contracts.canonical import canonical_contract_digest, canonical_json_digest
from raes_contracts.contracts import ParticipantConfigurationModel, ParticipantImplementationManifestModel
from raes_contracts.contracts.experiment_bindings import ParticipantControlContextConfigurationSelectionModel
from raes_env_packs import PackExperiment

#: ``(owner, family digest, requests) -> results``; each result has ``input_digest``,
#: ``normalized`` and ``contexts`` (the SDK ``ParticipantValidation``).
OwnerValidation = Callable[[str, str, list[dict[str, Any]]], Sequence[Any]]


def validation_requests(
    experiment: PackExperiment, address: str, manifest: ParticipantImplementationManifestModel
) -> list[dict[str, Any]]:
    """Return one request per distinct override set the experiment binds for a participant."""
    descriptors = experiment.experiment.binding_descriptors
    overrides: dict[str, list[dict[str, Any]]] = {}
    for item in descriptors.descriptors if descriptors is not None else ():
        target = item.target
        if target.plane == "participant-implementation" and target.participant_address == address:
            overrides.setdefault(item.source_condition_id, []).append(
                {"target_id": target.target_id, "value": item.value.model_dump(mode="json")}
            )
    ordered = [sorted(o, key=lambda v: v["target_id"]) for o in overrides.values()]
    distinct = {canonical_json_digest(o): o for o in ordered}
    payload = manifest.model_dump(mode="json")
    return [
        {"participant_address": address, "participant_manifest": payload, "overrides": o}
        for _, o in sorted(distinct.items())
    ]


class ReplayedConfigurationValidator:
    """Admit only the adapter-validated configurations and selections."""

    def __init__(
        self, normalized: dict[str, ParticipantConfigurationModel], contexts: frozenset[tuple[str, str]]
    ) -> None:
        self._normalized, self._contexts = normalized, contexts

    @classmethod
    def from_results(cls, requests: list[dict[str, Any]], results: Sequence[Any]) -> ReplayedConfigurationValidator:
        """Bind each owner result to its request; a count mismatch refuses."""
        if len(results) != len(requests):
            raise ValueError("Participant owner results do not match the requests")
        normalized: dict[str, ParticipantConfigurationModel] = {}
        contexts: set[tuple[str, str]] = set()
        for request, result in zip(requests, results, strict=True):
            normalized[result.input_digest] = ParticipantConfigurationModel.model_validate(result.normalized)
            contexts.update((request["participant_address"], canonical_json_digest(item)) for item in result.contexts)
        return cls(normalized, frozenset(contexts))

    def for_scenario(self, _scenario: object) -> ReplayedConfigurationValidator:
        """The owner validated against the admitted family; selection changes no reference."""
        return self

    def validate_and_normalize(self, configuration: ParticipantConfigurationModel) -> ParticipantConfigurationModel:
        """Return the owner's normalized configuration, or refuse an unvalidated one."""
        normalized = self._normalized.get(canonical_contract_digest(configuration))
        if normalized is None:
            raise ValueError("Participant configuration was not validated by its owner")
        return normalized.model_copy(deep=True)

    def validate_control_context_reference(
        self, participant_address: str, selection: ParticipantControlContextConfigurationSelectionModel
    ) -> None:
        """Accept only a selection that the owner accepted for this participant."""
        key = (participant_address, canonical_json_digest(selection.model_dump(mode="json")))
        if key not in self._contexts:
            raise ValueError("Control-context selection was not validated by its owner")

"""RAES apparatus documents that BigRAE derives for one disposable worker trial (issue #2928).

A worker trial runs inside one disposable GCE VM that boots from a published
worker host profile. BigRAE does not realize the authored scenario on that VM:
the profile's pinned image and the installed apparatus do. Each claim comes from
the party that realizes it: BigRAE states the host from the bound profile, and
the apparatus states what it realizes on that host in its declaration. An
authority that supplies its own documents keeps that path.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from raes import InstantiatedScenario
from raes_contracts.contracts import (
    BackendManifestV2Model,
    ObservationCaptureOfferModel,
    OrchestratorCapabilitiesModel,
    ParticipantRuntimeCapabilitiesModel,
    TimeCapabilitiesModel,
)
from raes_contracts.contracts.capabilities import (
    OperatingSystemCompatibilityModel,
    RealizationObservationCapabilityModel,
)
from raes_contracts.realization_envelope import (
    BackendRealizationEnvelopeModel,
    RealizationConcern,
    RealizationConcernDisclosureModel,
    RealizerConfigurationModel,
    realization_envelope_digest,
    realizer_configuration_digest,
)

from shared.disposable_workers import WorkerHostProfile
from shared.raes.contracts import SHIFTER_BACKEND_NAME

#: GCE machine families whose CPU architecture is fixed by the family name.
#: The default E2 custom shape is x86-64. Any other family fails closed.
_FAMILY_ARCHITECTURE = {"c4a": "aarch64", "t2a": "aarch64", "e2": "x86_64"}

#: The verification method of a cleanup probe reference ``absence:<boundary>``.
WORKER_ABSENCE_PROBE = "absence"

#: The worker GCE realizer boots the profile image, not the authored node source,
#: and sizes the host from the profile, not from the authored node resources.
#: GCE reports the machine type and image that worker qualification compares.
_REALIZED = {
    RealizationConcern.COMPUTE_SUBSTRATE: ("realized", [], "virtual-machine"),
    RealizationConcern.ARCHITECTURE: ("realized", [], "gce-machine-type"),
    RealizationConcern.IMAGE: ("transformed", ["image-substitution"], "gce-worker-profile-image"),
    RealizationConcern.RESOURCE_ALLOCATION: ("transformed", ["default-substitution"], "gce-worker-profile-shape"),
}


class ApparatusDeclaration(BaseModel):
    """What the installed apparatus realizes on the worker host, as its plugin declares it.

    BigRAE owns the host concerns that the bound profile states, so the apparatus
    cannot claim them. Every other claim reaches the derived documents unchanged.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["bigrae.apparatus-declaration/v1"]
    operating_systems: list[OperatingSystemCompatibilityModel] = Field(default_factory=list, max_length=64)
    supported_content_types: list[str] = Field(default_factory=list, max_length=64)
    supported_account_features: list[str] = Field(default_factory=list, max_length=64)
    concerns: list[RealizationConcernDisclosureModel] = Field(default_factory=list, max_length=16)
    exact_requirement_kinds: list[str] = Field(default_factory=list, max_length=64)
    constraint_kinds: list[str] = Field(default_factory=list, max_length=64)
    observation_capabilities: dict[str, RealizationObservationCapabilityModel] = Field(default_factory=dict)
    capture_offers: list[ObservationCaptureOfferModel] = Field(min_length=1, max_length=256)
    participant_runtime: ParticipantRuntimeCapabilitiesModel | None = None
    time: TimeCapabilitiesModel | None = None
    orchestrator: OrchestratorCapabilitiesModel | None = None
    contract_versions: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def _no_host_claims(self) -> ApparatusDeclaration:
        """Refuse a claim for a concern that BigRAE realizes from the profile, or a repeated concern."""
        claimed = [claim.concern for claim in self.concerns]
        if set(claimed) & set(_REALIZED) or len(claimed) != len(set(claimed)):
            raise ValueError("The apparatus declaration claims a host concern or repeats a concern")
        return self


def worker_architecture(profile: WorkerHostProfile) -> str:
    """Return the one governed CPU architecture term of every worker VM's GCE machine family."""
    families = {str(host["machine_type"]).split("-", 1)[0] for host in profile.hardware.values()}
    architectures = {_FAMILY_ARCHITECTURE[family] for family in families if family in _FAMILY_ARCHITECTURE}
    if len(architectures) != 1 or not families <= _FAMILY_ARCHITECTURE.keys():
        raise ValueError("Worker VMs need one known CPU architecture")
    return architectures.pop()


def worker_realization_envelope(
    profile: WorkerHostProfile, apparatus: ApparatusDeclaration
) -> BackendRealizationEnvelopeModel:
    """Derive the realization envelope of one worker host; a concern nobody claims is unsupported.

    An envelope path cannot address an imported node, whose name contains a dot, so
    :func:`require_worker_scenario` checks each selected scenario against the host.
    """
    nodes = profile.nodes
    cpus, mebibytes = [node.cpu for node in nodes], [node.ram // 1024**2 for node in nodes]
    fields = {
        "mode": "disposable-worker",
        "architecture": worker_architecture(profile),
        "image_policy": "worker-profile-image",
        "network_policy": f"worker-egress-{profile.egress_mode}",
        "supported_node_types": ["compute"],
        "supported_os_families": ["linux"],
        "memory_mib": {"minimum": min(mebibytes), "maximum": max(mebibytes)},
        "vcpus": {"minimum": min(cpus), "maximum": max(cpus)},
        "operating_systems": [row.model_dump(mode="json") for row in apparatus.operating_systems],
        "supported_content_types": apparatus.supported_content_types,
        "supported_account_features": apparatus.supported_account_features,
    }
    # The public digest helper validates the complete model before it excludes the self-digest.
    configuration = RealizerConfigurationModel(configuration_digest="sha256:" + "0" * 64, **fields)
    configuration = configuration.model_copy(
        update={"configuration_digest": realizer_configuration_digest(configuration)}
    )
    declared = {claim.concern: claim.model_dump(mode="json") for claim in apparatus.concerns}
    concerns = []
    for concern in RealizationConcern:
        disposition, transformations, mechanism = _REALIZED.get(concern, ("unsupported", [], None))
        concerns.append(
            declared.get(concern)
            or {
                "concern": concern.value,
                "disposition": disposition,
                "observation_strength": "none" if mechanism is None else "driver-reported",
                "mechanism": mechanism,
                "transformations": transformations,
            }
        )
    envelope_id = f"{SHIFTER_BACKEND_NAME}-disposable-worker-v1"
    payload = {
        "id": envelope_id,
        "expression": {"id": envelope_id, "scope": "scenario"},
        "configuration": configuration,
        "concerns": concerns,
    }
    return BackendRealizationEnvelopeModel(**payload, digest=realization_envelope_digest(payload))


def require_worker_scenario(scenario: InstantiatedScenario, profile: WorkerHostProfile, architecture: str) -> None:
    """Refuse a selected scenario unless it has one Linux compute node of the hosts' architecture per worker VM."""
    nodes = list(scenario.nodes.values())
    if len(nodes) != len(profile.nodes) or any(
        (node.type, node.os, node.architecture) != ("compute", "linux", architecture) for node in nodes
    ):
        raise ValueError("Worker hosts cannot realize the selected scenario nodes")


def _union(offers: Iterable[ObservationCaptureOfferModel], field: str) -> list[str]:
    """Return the sorted terms that any offer declares in ``field``, a term or a term list."""
    values = (getattr(offer, field) for offer in offers)
    return sorted({term for value in values for term in ([value] if isinstance(value, str) else value)})


def worker_backend_manifest(
    envelope: BackendRealizationEnvelopeModel, apparatus: ApparatusDeclaration, node_count: int = 1
) -> BackendManifestV2Model:
    """Derive the backend manifest of one worker host and the apparatus claims it carries."""
    configuration, capture_offers = envelope.configuration, apparatus.capture_offers
    # RAES requires all four experiment contracts for any observation capability.
    # BigRAE seals a partial run record and evidence records; it computes no derived measure.
    contracts = {
        "backend-manifest-v2",
        "realization-envelope-v1",
        "experiment-capture-spec-v1",
        "experiment-evidence-record-v1",
        "experiment-derived-measure-v1",
        "experiment-run-v1",
        "trial-cleanup-plan-v1",
        "trial-cleanup-receipt-v1",
        *_union(capture_offers, "output_contract"),
        *apparatus.contract_versions,
    }
    host_kinds = {"node-architecture", "node-type", "os-family"}
    optional = {
        key: value.model_dump(mode="json")
        for key, value in (
            ("participant_runtime", apparatus.participant_runtime),
            ("time", apparatus.time),
            ("orchestrator", apparatus.orchestrator),
        )
        if value is not None
    }
    return BackendManifestV2Model.model_validate(
        {
            "identity": {"name": f"{SHIFTER_BACKEND_NAME}-disposable-worker", "version": "1"},
            "supported_contract_versions": sorted(contracts),
            "compatibility": {"processors": ["raes-reference-processor"]},
            "realization_support": [
                {
                    "domain": "runtime-realization",
                    "support_mode": "constrained",
                    "supported_constraint_kinds": sorted(host_kinds | set(apparatus.constraint_kinds)),
                    "supported_exact_requirement_kinds": sorted(apparatus.exact_requirement_kinds),
                    "disclosure_kinds": ["backend-manifest-v2"],
                    "observation_capabilities": {
                        key: value.model_dump(mode="json") for key, value in apparatus.observation_capabilities.items()
                    },
                }
            ],
            "realization_envelope": envelope.identity.model_dump(mode="json"),
            "concept_bindings": [
                {"scope": "capabilities.provisioner.supported_node_types", "family": "assets"},
                {"scope": "capabilities.provisioner.supported_os_families", "family": "assets"},
                {"scope": "capabilities.provisioner.supported_node_architectures", "family": "assets"},
            ],
            "capabilities": {
                "provisioner": {
                    "name": f"{SHIFTER_BACKEND_NAME}-disposable-worker",
                    "supported_node_types": configuration.supported_node_types,
                    "supported_os_families": configuration.supported_os_families,
                    "supported_node_architectures": [configuration.architecture],
                    "operating_systems": [row.model_dump(mode="json") for row in configuration.operating_systems],
                    "supported_content_types": configuration.supported_content_types,
                    "supported_account_features": configuration.supported_account_features,
                    "supports_accounts": bool(configuration.supported_account_features),
                    "max_total_nodes": node_count,
                },
                # BigRAE collects a worker trial's evidence as one sealed file archive:
                # evidence records and a partial run record. The apparatus offers the captures.
                "observation": {
                    "name": f"{SHIFTER_BACKEND_NAME}-worker-trial-seal",
                    "supported_capture_kinds": _union(capture_offers, "capture_kind"),
                    "supported_channel_kinds": ["file-artifact"],
                    "supported_evidence_contracts": ["experiment-evidence-record-v1", "experiment-run-v1"],
                    "supported_media_types": _union(capture_offers, "media_types"),
                    "supported_sealing_modes": ["digest"],
                    "capture_offers": [offer.model_dump(mode="json") for offer in capture_offers],
                },
                # BigRAE destroys each trial's worker VM and records cleanup only after the
                # provider reports the VM absent. It writes no receipt for a failed cleanup,
                # so it does not claim residual-state disclosure.
                "cleanup": {
                    "name": f"{SHIFTER_BACKEND_NAME}-worker-retirement",
                    "supported_contract_versions": ["trial-cleanup-plan-v1", "trial-cleanup-receipt-v1"],
                    "supported_action_kinds": ["destroy"],
                    "supported_verification_methods": [WORKER_ABSENCE_PROBE],
                },
                **optional,
            },
        }
    )


__all__ = [
    "WORKER_ABSENCE_PROBE",
    "ApparatusDeclaration",
    "require_worker_scenario",
    "worker_architecture",
    "worker_backend_manifest",
    "worker_realization_envelope",
]

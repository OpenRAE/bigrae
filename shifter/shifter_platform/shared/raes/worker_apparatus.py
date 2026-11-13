"""RAES apparatus documents that BigRAE derives for one disposable worker trial (issue #2928).

A worker trial runs inside one disposable GCE VM that boots from a published
worker host profile. BigRAE does not realize the authored scenario on that VM:
the profile's pinned image and the installed apparatus do. These documents claim
only what BigRAE itself realizes for the host, and every claim comes from the
bound profile. An authority that supplies its own documents keeps that path.
"""

from __future__ import annotations

from collections.abc import Iterable

from raes import InstantiatedScenario
from raes_contracts.contracts import BackendManifestV2Model, ObservationCaptureOfferModel
from raes_contracts.realization_envelope import (
    BackendRealizationEnvelopeModel,
    RealizationConcern,
    RealizerConfigurationModel,
    realization_envelope_digest,
    realizer_configuration_digest,
)

from shared.disposable_workers import WorkerHostProfile
from shared.raes.contracts import SHIFTER_BACKEND_NAME
from shared.raes.worker_host import worker_host_shape

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


def worker_architecture(profile: WorkerHostProfile) -> str:
    """Return the governed CPU architecture term of the profile's GCE machine family."""
    family = str(profile.hardware["machine_type"]).split("-", 1)[0]
    if family not in _FAMILY_ARCHITECTURE:
        raise ValueError("Worker machine family has no known CPU architecture")
    return _FAMILY_ARCHITECTURE[family]


def worker_realization_envelope(profile: WorkerHostProfile) -> BackendRealizationEnvelopeModel:
    """Derive the realization envelope of one worker host; unrealized concerns are unsupported.

    An envelope path cannot address an imported node, whose name contains a dot, so
    :func:`require_worker_scenario` checks each selected scenario against the host.
    """
    _, _, _, cpu, ram = worker_host_shape(profile.plan)
    fields = {
        "mode": "disposable-worker",
        "architecture": worker_architecture(profile),
        "image_policy": "worker-profile-image",
        "network_policy": f"worker-egress-{profile.egress_mode}",
        "supported_node_types": ["compute"],
        "supported_os_families": ["linux"],
        "memory_mib": {"minimum": ram // 1024**2, "maximum": ram // 1024**2},
        "vcpus": {"minimum": cpu, "maximum": cpu},
    }
    # The public digest helper validates the complete model before it excludes the self-digest.
    configuration = RealizerConfigurationModel(configuration_digest="sha256:" + "0" * 64, **fields)
    configuration = configuration.model_copy(
        update={"configuration_digest": realizer_configuration_digest(configuration)}
    )
    concerns = []
    for concern in RealizationConcern:
        disposition, transformations, mechanism = _REALIZED.get(concern, ("unsupported", [], None))
        concerns.append(
            {
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


def require_worker_scenario(scenario: InstantiatedScenario, configuration: RealizerConfigurationModel) -> None:
    """Refuse a selected scenario unless its one node is a Linux compute node of the host's architecture."""
    nodes = list(scenario.nodes.values())
    if len(nodes) != 1 or (nodes[0].type, nodes[0].os, nodes[0].architecture) != (
        "compute",
        "linux",
        configuration.architecture,
    ):
        raise ValueError("Worker host cannot realize the selected scenario node")


def _union(offers: Iterable[ObservationCaptureOfferModel], field: str) -> list[str]:
    """Return the sorted terms that any offer declares in ``field``, a term or a term list."""
    values = (getattr(offer, field) for offer in offers)
    return sorted({term for value in values for term in ([value] if isinstance(value, str) else value)})


def worker_backend_manifest(
    envelope: BackendRealizationEnvelopeModel, capture_offers: list[ObservationCaptureOfferModel]
) -> BackendManifestV2Model:
    """Derive the backend manifest of one worker host and the apparatus capture offers it carries."""
    configuration = envelope.configuration
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
                    "supported_constraint_kinds": ["node-architecture", "node-type", "os-family"],
                    "disclosure_kinds": ["backend-manifest-v2"],
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
                    "max_total_nodes": 1,
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
            },
        }
    )


__all__ = [
    "WORKER_ABSENCE_PROBE",
    "require_worker_scenario",
    "worker_architecture",
    "worker_backend_manifest",
    "worker_realization_envelope",
]

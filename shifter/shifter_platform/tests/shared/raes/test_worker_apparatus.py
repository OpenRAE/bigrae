"""#2928: BigRAE derives worker-trial apparatus documents from the bound host profile."""

import json

import pytest
from raes.instantiate import instantiate_scenario
from raes.scenarios import load_scenario
from raes_backend_protocols.manifest import backend_manifest_from_v2_model_with_envelope
from raes_backend_protocols.trial_control_admission import require_trial_control_capability
from raes_contracts.contracts import (
    AdmittedExecutionControlModel,
    ObservationCaptureOfferModel,
    TrialExecutionAuthorityModel,
)
from raes_contracts.errors import ConflictError

from shared.disposable_workers import WorkerHostProfile
from shared.raes.experiment_admission import ExperimentAuthority
from shared.raes.worker_apparatus import (
    require_worker_scenario,
    worker_architecture,
    worker_backend_manifest,
    worker_realization_envelope,
)
from tests.engine.services.test_disposable_worker_profile import arm_profile_data, profile_data

OFFER = {
    "offer_id": "trial-transcript",
    "offer_version": "1",
    "output_contract": "experiment-evidence-record-v1",
    "field_selectors": [""],
    "artifact_roles": ["transcript"],
    "media_types": ["application/json"],
    "capture_kind": "artifact",
    "source_classes": ["experiment-capture-spec"],
    "scopes": ["run"],
    "channel_kinds": ["file-artifact"],
    "window_kinds": ["run"],
    "integrity_modes": ["digest"],
    "sensitivity": "internal",
    "availability": "available",
    "fidelity": "complete",
    "disclosure": "full",
    "export_policy": "not-required",
}


def _authority(requirement):
    """A worker trial's execution authority: one fresh VM, destroyed and verified absent."""
    return TrialExecutionAuthorityModel.model_validate(
        {
            "attempt_timeout_seconds": 1800,
            "on_cancellation": "cleanup-and-fail",
            "on_timeout": "cleanup-and-fail",
            "cleanup": {
                "clean_state": {
                    "boundary_refs": ["worker"],
                    "mode": "fresh",
                    "verification_probe_refs": ["absence:vm"],
                },
                "cleanup_obligations": {
                    "destroy": {
                        "obligation_id": "destroy",
                        "action_kind": "destroy",
                        "boundary_refs": ["worker"],
                        "idempotency": "idempotent",
                        "requirement": requirement,
                        "timeout_seconds": 600,
                        "triggers": ["success", "failure", "cancellation", "timeout", "abort"],
                        "verification_probe_refs": ["absence:vm"],
                    }
                },
                "resource_boundaries": {
                    "worker": {
                        "boundary_id": "worker",
                        "owner_ref": "apparatus:bigrae",
                        "resource_kind": "virtual-machine",
                        "resource_refs": ["worker:trial"],
                    }
                },
                "retry_policy": {"after_effect_policy": "disallow", "max_attempts": 1},
            },
        }
    )


@pytest.mark.parametrize(
    ("data", "architecture"),
    [
        (arm_profile_data(), "aarch64"),
        (profile_data(), "x86_64"),
        (profile_data() | {"image": profile_data()["image"] | {"machine_type": "n2-standard-2"}}, None),
    ],
)
def test_architecture_follows_the_gce_machine_family_and_fails_closed(data, architecture):
    profile = WorkerHostProfile.model_validate(data)
    if architecture is None:
        with pytest.raises(ValueError, match="CPU architecture"):
            worker_architecture(profile)
    else:
        assert worker_architecture(profile) == architecture


def test_derived_documents_claim_only_the_host_that_bigrae_realizes():
    envelope = worker_realization_envelope(WorkerHostProfile.model_validate(arm_profile_data()))
    claims = {claim.concern.value: (claim.disposition.value, claim.mechanism) for claim in envelope.concerns}
    assert {concern for concern, (disposition, _) in claims.items() if disposition != "unsupported"} == {
        "compute-substrate",
        "architecture",
        "image",
        "resource-allocation",
    }
    assert claims["image"] == ("transformed", "gce-worker-profile-image")
    configuration = envelope.configuration
    assert (configuration.architecture, configuration.vcpus.maximum, configuration.memory_mib.maximum) == (
        "aarch64",
        2,
        8192,
    )
    assert configuration.network_policy == "worker-egress-none"

    backend = worker_backend_manifest(envelope, [ObservationCaptureOfferModel.model_validate(OFFER)])
    assert backend.realization_envelope == envelope.identity
    provisioner, observation = backend.capabilities.provisioner, backend.capabilities.observation
    assert (provisioner.supported_node_architectures, provisioner.max_total_nodes) == (["aarch64"], 1)
    assert [offer.offer_id for offer in observation.capture_offers] == ["trial-transcript"]
    assert (observation.supported_channel_kinds, observation.supported_sealing_modes) == (["file-artifact"], ["digest"])
    # The RAES compiler rebuilds the manifest with its envelope and checks trial control.
    rebuilt = backend_manifest_from_v2_model_with_envelope(backend, envelope)
    control = AdmittedExecutionControlModel(
        attempt_timeout_seconds=1800,
        cleanup_plan_ref="cleanup",
        on_cancellation="cleanup-and-fail",
        on_timeout="cleanup-and-fail",
    )
    require_trial_control_capability(rebuilt, control, _authority("best-effort").cleanup)
    # BigRAE writes no receipt for a failed cleanup, so required cleanup is refused.
    with pytest.raises(ConflictError, match="residual-state"):
        require_trial_control_capability(rebuilt, control, _authority("required").cleanup)


@pytest.mark.parametrize(
    ("node", "admitted"),
    [
        ("{type: compute, os: linux, architecture: arm64}", True),
        ("{type: compute, os: linux, architecture: x86_64}", False),
        ("{type: compute, os: windows, architecture: arm64}", False),
    ],
)
def test_selected_scenario_must_be_one_node_of_the_host(tmp_path, node, admitted):
    path = tmp_path / "scenario.sdl.yaml"
    path.write_text(f"name: worker-trial\nnodes:\n  target: {node}\n")
    scenario = instantiate_scenario(load_scenario(path))
    configuration = worker_realization_envelope(WorkerHostProfile.model_validate(arm_profile_data())).configuration
    if admitted:
        require_worker_scenario(scenario, configuration)
    else:
        with pytest.raises(ValueError, match="selected scenario node"):
            require_worker_scenario(scenario, configuration)


def test_two_nodes_are_refused(tmp_path):
    path = tmp_path / "scenario.sdl.yaml"
    path.write_text("name: worker-trial\nnodes:\n  a: {type: compute, os: linux}\n  b: {type: compute, os: linux}\n")
    configuration = worker_realization_envelope(WorkerHostProfile.model_validate(profile_data())).configuration
    with pytest.raises(ValueError, match="selected scenario node"):
        require_worker_scenario(instantiate_scenario(load_scenario(path)), configuration)


@pytest.mark.parametrize(
    ("drop", "offers", "valid"),
    [
        ((), False, True),
        (("backend", "realization_envelope"), True, True),
        (("backend",), True, False),
        (("realization_envelope",), False, False),
        ((), True, False),
        (("backend", "realization_envelope"), False, False),
    ],
)
def test_authority_supplies_both_documents_or_only_capture_offers(drop, offers, valid):
    from tests.cms.experiment_admission_fixtures import FIXTURE

    authority = {"schema_version": "bigrae.experiment-admission-authority/v1"}
    for key, filename in (
        ("backend", "backend-manifest.json"),
        ("processor", "processor-manifest.json"),
        ("realization_envelope", "realization-envelope.json"),
        ("execution_authority", "execution-authority.json"),
    ):
        if key not in drop:
            authority[key] = json.loads((FIXTURE / "apparatus" / filename).read_text())
    if offers:
        authority["capture_offers"] = [OFFER]
    if valid:
        ExperimentAuthority.model_validate(authority)
    else:
        with pytest.raises(ValueError, match="capture offers only"):
            ExperimentAuthority.model_validate(authority)

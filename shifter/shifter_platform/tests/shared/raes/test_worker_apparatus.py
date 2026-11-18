"""#2928: BigRAE derives worker-trial apparatus documents from the bound host profile."""

import json

import pytest
from raes.instantiate import instantiate_scenario
from raes.scenarios import load_scenario
from raes_backend_protocols.manifest import backend_manifest_from_v2_model_with_envelope
from raes_backend_protocols.trial_control_admission import require_trial_control_capability
from raes_contracts.contracts import (
    AdmittedExecutionControlModel,
    TrialExecutionAuthorityModel,
)
from raes_contracts.errors import ConflictError

from shared.disposable_workers import WorkerHostProfile
from shared.raes.experiment_admission import ExperimentAuthority
from shared.raes.worker_apparatus import (
    ApparatusDeclaration,
    require_worker_scenario,
    worker_architecture,
    worker_backend_manifest,
    worker_realization_envelope,
)
from tests.engine.services.test_disposable_worker_profile import arm_profile_data, profile_data, two_vm_profile_data

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


APPARATUS = {"schema_version": "bigrae.apparatus-declaration/v1", "capture_offers": [OFFER]}
#: An apparatus that creates accounts and places files, and reads both back in the guest.
REALIZER = APPARATUS | {
    "operating_systems": [{"family": "linux", "distribution": "ubuntu", "versions": ["24.04"]}],
    "supported_content_types": ["file"],
    "supported_account_features": ["auth_method"],
    "concerns": [
        {"concern": c, "disposition": "realized", "observation_strength": "guest-observed", "mechanism": "readback"}
        for c in ("operating-system", "content-placement", "account-placement")
    ],
    "exact_requirement_kinds": ["declared-capability-match"],
    "constraint_kinds": ["account-feature", "content-type"],
    "observation_capabilities": {
        "operating-system": {"verification_scope": "presence", "observation_strength": "guest-observed"}
    },
}


def _declaration(data=APPARATUS):
    return ApparatusDeclaration.model_validate(data)


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
    envelope = worker_realization_envelope(WorkerHostProfile.model_validate(arm_profile_data()), _declaration())
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

    backend = worker_backend_manifest(envelope, _declaration())
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
    profile = WorkerHostProfile.model_validate(arm_profile_data())
    if admitted:
        require_worker_scenario(scenario, profile, "aarch64")
    else:
        with pytest.raises(ValueError, match="selected scenario nodes"):
            require_worker_scenario(scenario, profile, "aarch64")


def test_a_scenario_needs_one_node_per_worker_vm(tmp_path):
    """#2947: a two-node scenario fits a two-VM worker and no other."""
    path = tmp_path / "scenario.sdl.yaml"
    path.write_text(
        "name: worker-trial\nnodes:\n  a: {type: compute, os: linux, architecture: x86_64}\n"
        "  b: {type: compute, os: linux, architecture: x86_64}\n"
    )
    scenario = instantiate_scenario(load_scenario(path))
    require_worker_scenario(scenario, WorkerHostProfile.model_validate(two_vm_profile_data()), "x86_64")
    with pytest.raises(ValueError, match="selected scenario nodes"):
        require_worker_scenario(scenario, WorkerHostProfile.model_validate(profile_data()), "x86_64")


@pytest.mark.parametrize(
    ("drop", "declared", "valid"),
    [
        ((), False, True),
        (("backend", "realization_envelope"), True, True),
        (("backend",), True, False),
        (("realization_envelope",), False, False),
        ((), True, False),
        (("backend", "realization_envelope"), False, False),
    ],
)
def test_authority_supplies_both_documents_or_only_the_apparatus_declaration(drop, declared, valid):
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
    if declared:
        authority["apparatus"] = APPARATUS
    if valid:
        ExperimentAuthority.model_validate(authority)
    else:
        with pytest.raises(ValueError, match="the declaration only"):
            ExperimentAuthority.model_validate(authority)


def test_apparatus_claims_reach_the_documents_and_host_claims_are_refused():
    """#2928: BigRAE states the host; the apparatus states only what it realizes on the host."""
    profile = WorkerHostProfile.model_validate(arm_profile_data())
    envelope = worker_realization_envelope(profile, _declaration(REALIZER))
    claims = {claim.concern.value: claim.disposition.value for claim in envelope.concerns}
    assert claims["account-placement"] == claims["operating-system"] == "realized"
    assert claims["compute-substrate"] == "realized" and claims["service"] == "unsupported"
    assert envelope.configuration.supported_account_features == ["auth_method"]
    backend = worker_backend_manifest(envelope, _declaration(REALIZER))
    provisioner = backend.capabilities.provisioner
    assert (provisioner.supports_accounts, provisioner.supported_content_types) == (True, ["file"])
    assert backend.realization_support[0].supported_exact_requirement_kinds == ["declared-capability-match"]
    host_claim = {
        "concern": "compute-substrate",
        "disposition": "realized",
        "observation_strength": "guest-observed",
        "mechanism": "virtual-machine",
    }
    for concerns in ([host_claim], [REALIZER["concerns"][0]] * 2):
        with pytest.raises(ValueError, match="host concern or repeats"):
            _declaration(APPARATUS | {"concerns": concerns})

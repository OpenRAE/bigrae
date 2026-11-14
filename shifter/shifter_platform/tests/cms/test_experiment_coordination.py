"""#2914: BigRAE coordinates an admitted batch in RAES and never runs a trial itself."""

import pytest
from raes import canonical_sdl_digest
from raes_contracts.errors import ConflictError
from raes_env_packs import load_pack_experiments
from raes_processor.trial_scheduler import plan_batch_schedule
from raes_runtime import RuntimeControlPlane

from shared.raes.experiment_coordination import (
    TRIAL_TARGET_NAME,
    CoordinatorTrialServices,
    assigned_trial_inputs,
    coordinator_target,
    realization_inputs,
)
from tests.cms.experiment_admission_fixtures import admit
from tests.cms.experiment_admission_fixtures import experiment_inputs as experiment_inputs
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody

pytestmark = pytest.mark.django_db


def _family(root):
    return next(
        item for item in load_pack_experiments(root) if item.experiment.spec_id == "fixture-crossed-design"
    ).family


def test_the_coordinator_admits_and_assigns_from_the_retained_inputs_without_running_a_trial(experiment_inputs):
    # The coordinator realizes every entry at admission, so the backend must support the fixture's scheduled jobs.
    support = experiment_inputs[-1]["backend"]["realization_support"][0]
    support["supported_exact_requirement_kinds"].append("runtime-scheduled-jobs")
    support["observation_capabilities"]["runtime-scheduled-jobs"] = {
        "verification_scope": "configuration",
        "observation_strength": "guest-observed",
    }
    batch = admit(experiment_inputs)
    family = _family(experiment_inputs[3])
    realization = realization_inputs(batch.inputs, family)
    target = coordinator_target(realization)
    services = CoordinatorTrialServices()
    with RuntimeControlPlane(target) as coordinator:
        experiment = coordinator.admit_experiment(realization, services=services)
        entry = plan_batch_schedule(realization.plan).entries[0].plan_entry_id
        assignment = coordinator.assign_trial(experiment, entry, owner_id="worker-a")
    assert (experiment, assignment.plan_entry_id) == (batch.inputs["plan"]["plan_id"], entry)
    assert assignment.target_scope == f"target:{TRIAL_TARGET_NAME}"
    for refused in (lambda: target.provisioner.apply(None, None), lambda: services.configure(None, None)):
        with pytest.raises(ConflictError, match="runs no trial"):
            refused()
    staged = assigned_trial_inputs(batch.inputs)
    assert staged.family_digest == canonical_sdl_digest(family).value
    assert {entry.kind for entry in staged.apparatus_manifests} == {"backend", "processor"}


def test_a_family_that_differs_from_the_admitted_one_is_refused(experiment_inputs):
    batch = admit(experiment_inputs)
    inputs = batch.inputs | {"family": batch.inputs["family"] | {"profile": "changed"}}
    with pytest.raises(ValueError, match="differs from the admitted family"):
        realization_inputs(inputs, _family(experiment_inputs[3]))


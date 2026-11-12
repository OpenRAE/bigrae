"""Reusable public installed-package inputs for experiment service tests."""

import json
import shutil
from pathlib import Path

import pytest

from cms.models import RaesPackageSource
from tests.cms.conftest import write_pack_content_manifest

FIXTURE = Path(__file__).parents[1] / "shared/raes/fixtures/experiment-admission"


def write_experiment_content_manifest(root):
    """Publish exact synthetic prompt descriptors with the installed owner contract."""
    from raes import admit_scenario_family, parse_sdl
    from raes_contracts.associated_artifacts import associated_artifact_set_digest
    from raes_contracts.contracts import AssociatedArtifactManifestModel

    write_pack_content_manifest(root, root.name)
    path = root / "associated-artifacts.json"
    manifest = AssociatedArtifactManifestModel.model_validate_json(path.read_bytes())
    family = admit_scenario_family(parse_sdl((root / "sdl/experiment-fixture.sdl.yaml").read_text()))
    for asset in family.control_context_assets.values():
        matched = [(key, value) for key, value in manifest.artifacts.items() if value.uri == asset.content.uri]
        if matched:
            key, actual = matched[0]
            del manifest.artifacts[key]
            manifest.artifacts[asset.content.artifact_id] = asset.content.model_copy(
                update={"checksum": actual.checksum, "size_bytes": actual.size_bytes}
            )
    manifest = manifest.model_copy(update={"set_digest": associated_artifact_set_digest(manifest)})
    path.write_text(manifest.model_dump_json(indent=2) + "\n")


@pytest.fixture
def experiment_inputs(custody, make_pack, tmp_path, settings):
    from cms.scenarios.pack_validation import pack_digest
    from engine.models import WorkerPolicyRecord
    from shared.disposable_workers import WorkerPolicy
    from tests.engine.services.test_disposable_worker_profile import profile_data

    actor, organization, _ = custody
    # Admission binds the batch to the published default worker host profile.
    WorkerPolicyRecord.objects.create(
        pk=1,
        configuration=WorkerPolicy(profiles={"default": profile_data()}, max_live=2, max_provisioning=2).model_dump(
            mode="json"
        ),
    )
    root = make_pack(tmp_path / "experiment-fixture", sdl=None)
    shutil.copytree(FIXTURE / "pack", root, dirs_exist_ok=True)
    write_experiment_content_manifest(root)
    settings.RAES_PACKAGE_ROOT = str(tmp_path)
    source = RaesPackageSource.objects.create(
        scenario_id="synthetic-experiment",
        package_name=root.name,
        source_kind="repo",
        contract_kind="raes",
        contract_profile="synthetic-admission",
        package_ref=root.name,
        package_version="0.1.0",
        package_digest=pack_digest(root),
        conformance_status="passed",
        owner_principal_uuid=actor.credential.principal.uuid,
        scope_kind="account",
        account_uuid=organization.account.uuid,
        organization_uuid=organization.uuid,
    )
    authority = {"schema_version": "bigrae.experiment-admission-authority/v1"}
    for key, filename in (
        ("backend", "backend-manifest.json"),
        ("processor", "processor-manifest.json"),
        ("realization_envelope", "realization-envelope.json"),
        ("execution_authority", "execution-authority.json"),
    ):
        authority[key] = json.loads((FIXTURE / "apparatus" / filename).read_text())
    manifest = json.loads((FIXTURE / "apparatus/participant-manifest.json").read_text())
    authority["participants"] = [
        {"participant_address": address, "manifest": manifest} for address in ("agents.operator", "agents.defender")
    ]
    actor.policy_accounts.add(None)
    return actor, organization, source, root, authority


def admit(inputs, **options):
    from cms.services import admit_experiment_batch

    actor, organization, source, _, authority = inputs
    return admit_experiment_batch(
        actor.credential,
        organization.uuid,
        scenario_id=source.scenario_id,
        experiment_id="fixture-crossed-design",
        authority=authority,
        concurrency=options.pop("concurrency", 1),
        **options,
    )

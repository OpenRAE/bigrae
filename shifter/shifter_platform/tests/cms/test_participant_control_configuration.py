"""Native control installation retains exact source, scope, proof and audit."""

from dataclasses import replace

import pytest

from cms.exceptions import CMSError
from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import pack_digest
from shared.exceptions import ValidationError
from tests.cms.test_runtime_plugins import tenant
from tests.shared.raes.test_native_power_package import selection
from tests.shared.raes.test_native_power_package import source as controlled_source

__all__ = ["controlled_source", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.fixture
def controlled_pack(tenant, controlled_source, make_pack, tmp_path, settings):
    from shared.participant_control_installation import NativeControlInstallation
    from tests.shared.test_participant_control_installation import synthetic_installation_values

    values = synthetic_installation_values()
    values["provisioner_image"] = "example.test/synthetic@sha256:" + "1" * 64
    settings.PARTICIPANT_CONTROL_INSTALLATION = NativeControlInstallation.model_validate(values)
    settings.ENGINE_TASK_DEFINITION = values["provisioner_image"]
    actor, organization = tenant
    name = "synthetic-native-power-admission"
    root = make_pack(tmp_path / name, sdl=controlled_source.read_text())
    settings.RAES_PACKAGE_ROOT = str(tmp_path)
    source = RaesPackageSource.objects.create(
        scenario_id=name,
        contract_kind="raes",
        contract_profile="shifter",
        package_ref=name,
        package_version="0.1.0",
        package_digest=pack_digest(root),
        owner_principal_uuid=actor.credential.principal.uuid,
        scope_kind="account",
        account_uuid=organization.account.uuid,
        organization_uuid=organization.uuid,
        registered_by=actor,
    )
    return actor, organization, source, root


def configure(item, *, chosen=None, digest=None, organization=None):
    from cms.services import configure_native_participant_control

    actor, org, source, _ = item
    return configure_native_participant_control(
        actor.credential,
        organization or org.uuid,
        source.scenario_id,
        expected_package_digest=digest or source.package_digest,
        selection=chosen or selection(),
    )


def test_configuration_is_scoped_idempotent_audited_and_has_no_execution_authority(controlled_pack):
    from cms.models import ParticipantControlConfiguration
    from engine.models import ParticipantPowerReservation, Range

    actor, organization, source, _ = controlled_pack
    result = configure(controlled_pack)
    assert configure(controlled_pack).id == result.id
    saved = ParticipantControlConfiguration.objects.get(pk=result.id)
    assert saved.organization_uuid == organization.uuid
    assert saved.source_uuid == source.pk
    assert saved.source_package_digest == source.package_digest
    assert saved.selection == selection()
    assert saved.initiating_principal_uuid == actor.credential.principal.uuid
    assert saved.structural_report_ref.startswith("urn:shifter:participant-control-source-check:")
    assert saved.raes_version == "10.6.0"
    assert saved.runtime_policy_digest == result.runtime_policy_digest
    assert saved.runtime_policy_digest.startswith("sha256:")
    source.refresh_from_db()
    assert source.conformance_status == "pending"
    assert not Range.objects.exists() and not ParticipantPowerReservation.objects.exists()


def test_source_configuration_requires_current_pinned_installation(controlled_pack, settings):
    from cms.models import ParticipantControlConfiguration

    settings.PARTICIPANT_CONTROL_INSTALLATION = None
    with pytest.raises(ValidationError, match="Native participant control installation unavailable"):
        configure(controlled_pack)
    assert not ParticipantControlConfiguration.objects.exists()


@pytest.mark.parametrize("fault", ["stale", "meaning", "authority", "tenant", "bytes"])
def test_unverified_or_foreign_configuration_creates_no_record(controlled_pack, fault):
    from cms.models import ParticipantControlConfiguration
    from workspaces.services import OrganizationAuthorizationError, create_account

    actor, _, _, root = controlled_pack
    kwargs = {}
    if fault == "stale":
        kwargs["digest"] = "sha256:" + "f" * 64
    elif fault == "meaning":
        kwargs["chosen"] = replace(selection(), pause_action_contract_address="participant.action-contract.foreign")
    elif fault == "authority":
        actor.policy_principals.clear()
    elif fault == "tenant":
        from workspaces.models import Organization

        other = create_account(kind="team", name="Another synthetic tenant")
        actor.policy_accounts.add(other.uuid)
        kwargs["organization"] = Organization.objects.get(account_id=other.id, is_default=True).uuid
    else:
        (root / "sdl/scenario.sdl.yaml").write_text("changed")
    with pytest.raises((ValidationError, CMSError, OrganizationAuthorizationError)):
        configure(controlled_pack, **kwargs)
    assert not ParticipantControlConfiguration.objects.exists()


def test_configuration_audit_failure_rolls_back_installation(controlled_pack, monkeypatch):
    from cms.models import ParticipantControlConfiguration

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic configuration audit unavailable")

    monkeypatch.setattr("cms.services._participant_control_configuration.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="configuration audit unavailable"):
        configure(controlled_pack)
    assert not ParticipantControlConfiguration.objects.exists()


def test_source_replacement_during_structure_check_cannot_commit(controlled_pack, monkeypatch):
    from cms.models import ParticipantControlConfiguration
    from cms.services import _participant_control_configuration as service

    validate = service.validate_native_power_configuration
    source = controlled_pack[2]

    def replace_after_check(*args, **kwargs):
        evidence = validate(*args, **kwargs)
        RaesPackageSource.objects.filter(pk=source.pk).update(package_digest="sha256:" + "c" * 64)
        return evidence

    monkeypatch.setattr(service, "validate_native_power_configuration", replace_after_check)
    with pytest.raises(ValidationError):
        configure(controlled_pack)
    assert not ParticipantControlConfiguration.objects.exists()


@pytest.mark.parametrize(
    "field",
    ["source_package_digest", "organization_uuid", "participant_address", "credential_uuid", "runtime_policy_digest"],
)
def test_configuration_identity_cannot_be_rewritten(controlled_pack, field):
    from uuid import uuid4

    from django.db import IntegrityError, transaction

    from cms.models import ParticipantControlConfiguration

    result = configure(controlled_pack)
    replacement = uuid4() if field.endswith("uuid") else "sha256:" + "d" * 64
    with pytest.raises(IntegrityError), transaction.atomic():
        ParticipantControlConfiguration.objects.filter(pk=result.id).update(**{field: replacement})


def test_retirement_cannot_be_reversed_or_changed(controlled_pack):
    from datetime import timedelta

    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from cms.models import ParticipantControlConfiguration

    result = configure(controlled_pack)
    rows = ParticipantControlConfiguration.objects.filter(pk=result.id)
    now = timezone.now()
    rows.update(retired_at=now)
    rows.update(retired_at=now)  # exact replay is harmless
    for replacement in (None, now + timedelta(seconds=1)):
        with pytest.raises(IntegrityError), transaction.atomic():
            rows.update(retired_at=replacement)


def make_binding(config_id, **changes):
    from uuid import uuid4

    from cms.models import ParticipantControlBinding, ParticipantControlConfiguration

    config = ParticipantControlConfiguration.objects.get(pk=config_id)
    values = {
        "configuration": config,
        "configuration_digest": config.configuration_digest,
        "range_uuid": uuid4(),
        "compiler_binding_ref": uuid4(),
        "resource_generation": uuid4(),
        "product": "ctf",
        "product_subject_uuid": uuid4(),
    }
    values.update(changes)
    return ParticipantControlBinding.objects.create(**values)


def test_live_binding_prevents_configuration_retirement(controlled_pack):
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from cms.models import ParticipantControlConfiguration

    result = configure(controlled_pack)
    binding = make_binding(result.id)
    with pytest.raises(IntegrityError), transaction.atomic():
        ParticipantControlConfiguration.objects.filter(pk=result.id).update(retired_at=timezone.now())
    binding.invalidated_at = timezone.now()
    binding.save(update_fields=["invalidated_at"])
    ParticipantControlConfiguration.objects.filter(pk=result.id).update(retired_at=timezone.now())


@pytest.mark.parametrize("fault", ["digest", "retired"])
def test_binding_cannot_install_against_a_different_or_retired_configuration(controlled_pack, fault):
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from cms.models import ParticipantControlConfiguration

    result = configure(controlled_pack)
    changes = {}
    if fault == "retired":
        ParticipantControlConfiguration.objects.filter(pk=result.id).update(retired_at=timezone.now())
    else:
        changes["configuration_digest"] = "sha256:" + "c" * 64
    with pytest.raises(IntegrityError), transaction.atomic():
        make_binding(result.id, **changes)


@pytest.mark.parametrize("field", ["resource_generation", "run_id", "compiler_binding_ref", "product_subject_uuid"])
def test_binding_identity_is_immutable_and_invalidation_is_irreversible(controlled_pack, field):
    from uuid import uuid4

    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from cms.models import ParticipantControlBinding

    binding = make_binding(configure(controlled_pack).id)
    rows = ParticipantControlBinding.objects.filter(pk=binding.pk)
    with pytest.raises(IntegrityError), transaction.atomic():
        rows.update(**{field: uuid4()})
    rows.update(invalidated_at=timezone.now())
    with pytest.raises(IntegrityError), transaction.atomic():
        rows.update(invalidated_at=None)

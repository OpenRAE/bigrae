"""Private compiler input is available only behind current native range authority."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from raes import parse_sdl
from raes_runtime import RuntimeManager

from engine.services import RangeBindings, create_raes_range
from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan
from tests.cms.test_runtime_plugins import tenant

__all__ = ["tenant"]
pytestmark = pytest.mark.django_db


class _NoDispatch:
    request_id = "synthetic"

    def realize(self, *args, **kwargs):
        raise AssertionError("Planning must not dispatch")


@pytest.fixture
def compiled_native(tenant, settings):
    source = Path(__file__).parents[2] / "shared/raes/fixtures/launchable/shifter-launch-access.sdl.yaml"
    authored = yaml.safe_load(source.read_text())
    authored["agents"]["analyst"]["operating_scope"] = ["nodes.web"]
    authored["variables"] = {"note": {"type": "string", "default": "fallback"}}
    scenario = parse_sdl(yaml.safe_dump(authored))
    return create_compiled_native_case(tenant, settings, scenario, {"note": "synthetic-private-parameter"}, _plan)


def _plan(scenario, parameters):
    target = create_shifter_backend_target(port=_NoDispatch(), scenario=scenario)
    return RuntimeManager(target).plan(scenario, parameters=parameters)


def create_compiled_native_case(
    tenant,
    settings,
    scenario,
    parameters,
    plan_builder,
    *,
    source_package_digest="sha256:" + "b" * 64,
    scenario_id="synthetic",
    event_uuid=None,
    before_engine_create=None,
):
    """Create actual CMS/Engine custody around a public SDK-produced plan."""
    from cms.models import RangeInstance
    from cms.models import Request as CmsRequest
    from engine.models import Range
    from shared.authorization import TargetRef
    from shared.operation_authority import credential_reference_fields
    from workspaces.services import add_account_member, hierarchy_target_scope, resolve_resource_scope

    actor, organization = tenant
    settings.CLOUD_PROVIDER = "aws"
    settings.ENGINE_TASK_CLUSTER = "synthetic-namespace"
    settings.ENGINE_TASK_DEFINITION = "example.test/synthetic@sha256:" + "1" * 64
    credential = actor.credential
    add_account_member(organization.account.uuid, credential.principal)
    scope = hierarchy_target_scope("organization", organization.uuid)
    resolved = resolve_resource_scope(scope)
    request_id = uuid4()
    custody = {
        "owner_principal_uuid": credential.principal.uuid,
        "scope_kind": "account",
        "account_id": resolved.account_id,
        "organization_id": resolved.organization_id,
    }
    cms_request = CmsRequest.objects.create(
        request_id=request_id,
        request_type="range",
        user=actor,
        **custody,
        **credential_reference_fields(credential),
    )
    instance = RangeInstance.objects.create(
        request=cms_request,
        user_id=actor.pk,
        scenario_id=scenario_id,
        event_uuid=event_uuid,
        range_source="ctf" if event_uuid is not None else "mission_control",
        **custody,
    )
    if before_engine_create is not None:
        before_engine_create(instance, request_id)
    plan = plan_builder(scenario, parameters)
    assert plan.is_valid
    context = project_compiled_participants(plan.model, parameters=parameters)
    create_raes_range(
        request_id=request_id,
        user_id=actor.pk,
        workspace_id=None,
        egress_mode="none",
        compiled_plan=serialize_provisioning_plan(plan.provisioning),
        bindings=RangeBindings(
            credential=credential,
            resource_scope=scope,
            cms_range_uuid=instance.uuid,
            defer_dispatch=True,
            compiled_participants=context,
            source_package_digest=source_package_digest,
            authority_action="event.manage_ranges" if event_uuid is not None else None,
            authority_target=TargetRef("event", event_uuid) if event_uuid is not None else None,
        ),
    )
    row = Range.objects.get(request__request_id=request_id)
    # This fixture supplies a synthetic realized generation without a cloud
    # launch. Keep its actual original immutable input, as production does.
    from engine.models import OperationInput
    from shared.operation_envelope import build_operation_envelope
    from shared.raes.operation_input import RaesInputBindings, RaesRangeIdentity, build_raes_operation_input

    original_id = uuid4()
    original = build_operation_envelope(
        operation_id=original_id,
        request_id=request_id,
        resource="raes-range",
        operation="provision",
        payload=build_raes_operation_input(
            plan=row.range_config,
            bindings=RaesInputBindings(delivery=[]),
            image_candidates={},
            range_backend="gce",
            instantiation_purpose=row.instantiation_purpose or None,
            identity=RaesRangeIdentity(row.pk, str(row.resource_generation)),
            egress_mode="none",
        ),
    )
    OperationInput.objects.create(
        operation_id=original_id,
        request_id=request_id,
        resource="raes-range",
        operation="provision",
        contract_version=original["contract_version"],
        envelope=original,
    )
    instance.range_id = row.pk
    instance.save(update_fields=["range_id"])
    return SimpleNamespace(
        row=row,
        actor=actor,
        credential=credential,
        request_id=request_id,
        context=context,
        scenario=scenario,
    )


def test_current_native_manager_reads_the_exact_retained_compiler_context(compiled_native):
    from engine.services import read_range_compiler_input

    case = compiled_native
    loaded = read_range_compiler_input(case.credential, case.request_id)
    assert loaded.context == case.context
    assert loaded.resource_generation == case.row.resource_generation
    assert loaded.source_package_digest == "sha256:" + "b" * 64
    assert loaded.binding_ref is not None
    assert "synthetic-private-parameter" not in repr(loaded)


def test_revoked_native_authority_cannot_read_compiler_input(compiled_native):
    from engine.services import read_range_compiler_input

    case = compiled_native
    case.actor.policy_principals.clear()
    with pytest.raises(PermissionError):
        read_range_compiler_input(case.credential, case.request_id)


def test_denied_native_request_does_not_attempt_private_decryption(compiled_native, settings):
    from cryptography.fernet import Fernet

    from engine.services import read_range_compiler_input

    case = compiled_native
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    case.actor.policy_principals.clear()
    with pytest.raises(PermissionError):
        read_range_compiler_input(case.credential, case.request_id)


def test_an_old_resource_generation_cannot_restore_a_compiler_context(compiled_native):
    from engine.services import EngineError, read_range_compiler_input

    case = compiled_native
    case.row.resource_generation = uuid4()
    case.row.save(update_fields=["resource_generation"])
    with pytest.raises(EngineError, match="Range compiler input is unavailable"):
        read_range_compiler_input(case.credential, case.request_id)


def test_event_override_cannot_borrow_an_unrelated_parent(compiled_native):
    from engine.services import read_range_compiler_input
    from shared.authorization import TargetRef

    case = compiled_native
    with pytest.raises(PermissionError):
        read_range_compiler_input(case.credential, case.request_id, authority_target=TargetRef("event", uuid4()))

"""A run binding joins genuine product, source, private compiler and native custody."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone
from raes.scenarios import load_scenario

from tests.cms.test_participant_control_configuration import configure, controlled_pack, controlled_source, tenant
from tests.engine.services.test_native_compiler_context import _NoDispatch, create_compiled_native_case
from tests.engine.services.test_native_participant_reservation import _native_action_case
from tests.shared.raes.test_native_power_package import selection

__all__ = ["controlled_pack", "controlled_source", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.fixture
def product_range(controlled_pack, settings):
    from cms.models import RangeInstance
    from ctf.models import CTFEvent, CTFParticipant
    from shared.raes.native_power_planning import plan_native_power_with_artifact_supply

    actor, organization, source, root = controlled_pack
    config = configure(controlled_pack)
    event = CTFEvent.objects.create(
        name="Synthetic controlled exercise",
        created_by=actor,
        owner_principal_uuid=actor.credential.principal.uuid,
        scope_kind="account",
        account_id=organization.account_id,
        organization_id=organization.pk,
        status="active",
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=1),
        scenario_id=source.scenario_id,
    )
    subjects = []

    def associate(instance, request_id):
        subjects.append(
            CTFParticipant.objects.create(
                event=event,
                user=actor,
                name="Synthetic subject",
                status="active",
                range_instance_id=instance.pk,
                range_request_id=request_id,
            )
        )

    def plan(scenario, parameters):
        execution, _ = plan_native_power_with_artifact_supply(
            scenario=scenario, parameters=parameters, selection=selection(), port=_NoDispatch()
        )
        return execution

    case = create_compiled_native_case(
        (actor, organization),
        settings,
        load_scenario(root / "sdl/scenario.sdl.yaml"),
        {},
        plan,
        source_package_digest=source.package_digest,
        scenario_id=source.scenario_id,
        event_uuid=event.pk,
        before_engine_create=associate,
    )
    _native_action_case(case, "pause")
    instance = RangeInstance.objects.get(request__request_id=case.request_id)
    instance.status = "ready"
    instance.save(update_fields=["status"])
    return SimpleNamespace(case=case, config=config, event=event, subject=subjects[0], instance=instance, source=source)


def bind(item, **changes):
    from cms.services import bind_native_participant_control

    values = {"product": "ctf", "subject_uuid": item.subject.pk, "configuration_id": item.config.id}
    values.update(changes)
    return bind_native_participant_control(item.case.credential, **values)


def test_binding_is_idempotent_for_exact_source_subject_and_generation(product_range):
    from cms.models import ParticipantControlBinding
    from engine.models import ParticipantPowerReservation

    item = product_range
    result = bind(item)
    assert bind(item) == result
    saved = ParticipantControlBinding.objects.get(pk=result.id)
    assert saved.range_uuid == item.instance.uuid
    assert saved.product_subject_uuid == item.subject.pk
    assert saved.configuration_digest == item.config.configuration_digest
    assert saved.resource_generation == item.case.row.resource_generation
    assert saved.initiating_principal_uuid == item.case.credential.principal.uuid
    assert result.coordinates.binding_ref == saved.compiler_binding_ref
    assert result.coordinates.run_id == saved.run_id
    assert not ParticipantPowerReservation.objects.exists()


def test_existing_owner_reuses_only_exact_immutable_source_qualification(product_range, monkeypatch):
    from django.db import transaction

    from cms.services import prepare_native_control_binding

    item = product_range
    view = bind(item)
    original = prepare_native_control_binding(item.case.credential, view.id)

    def unexpected_compile(*args, **kwargs):
        raise AssertionError("An existing immutable qualification must not be compiled again")

    monkeypatch.setattr(
        "cms.services._participant_control_input.validate_bound_native_power_source", unexpected_compile
    )
    current = prepare_native_control_binding(item.case.credential, view.id, qualification=original)
    with transaction.atomic():
        assert current.fence() == original.native.input


def test_cached_source_qualification_never_authorizes_changed_source_custody(product_range):
    from cms.models import RaesPackageSource
    from cms.services import prepare_native_control_binding
    from shared.exceptions import ValidationError

    item = product_range
    view = bind(item)
    original = prepare_native_control_binding(item.case.credential, view.id)
    RaesPackageSource.objects.filter(pk=item.source.pk).update(scope_generation=item.source.scope_generation + 1)
    with pytest.raises(ValidationError, match="Native participant control binding unavailable"):
        prepare_native_control_binding(item.case.credential, view.id, qualification=original)


def test_deployment_image_change_cannot_reuse_an_old_control_binding(product_range, settings):
    from cms.services import prepare_native_control_binding
    from shared.exceptions import ValidationError

    item = product_range
    view = bind(item)
    original = prepare_native_control_binding(item.case.credential, view.id)
    settings.ENGINE_TASK_DEFINITION = "example.test/new-release@sha256:" + "8" * 64
    with pytest.raises(ValidationError):
        prepare_native_control_binding(item.case.credential, view.id, qualification=original)


@pytest.mark.parametrize("fault", ["configuration", "source", "authority", "subject", "generation", "source-custody"])
def test_unqualified_binding_never_allocates_a_run(product_range, fault):
    from cms.models import ParticipantControlBinding, RaesPackageSource
    from shared.exceptions import ValidationError

    item = product_range
    changes = {}
    if fault == "configuration":
        changes["configuration_id"] = uuid4()
    elif fault == "source":
        RaesPackageSource.objects.filter(pk=item.source.pk).update(package_digest="sha256:" + "f" * 64)
    elif fault == "authority":
        item.case.actor.policy_principals.clear()
    elif fault == "subject":
        changes["subject_uuid"] = uuid4()
    elif fault == "generation":
        item.case.row.resource_generation = uuid4()
        item.case.row.save(update_fields=["resource_generation"])
    else:
        RaesPackageSource.objects.filter(pk=item.source.pk).update(organization_uuid=uuid4())
    with pytest.raises(ValidationError):
        bind(item, **changes)
    assert not ParticipantControlBinding.objects.exists()


def test_binding_audit_failure_rolls_back_run_allocation(product_range, monkeypatch):
    from cms.models import ParticipantControlBinding

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic binding audit unavailable")

    monkeypatch.setattr("cms.services._participant_control_binding.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="binding audit unavailable"):
        bind(product_range)
    assert not ParticipantControlBinding.objects.exists()


@pytest.mark.parametrize("fault", ["native-generation", "product-assignment", "retired-config", "source-custody"])
def test_binding_fences_changes_after_private_qualification(product_range, monkeypatch, fault):
    from cms.models import ParticipantControlBinding, ParticipantControlConfiguration, RaesPackageSource
    from cms.services import _participant_control_input as service
    from ctf.models import CTFParticipant
    from shared.exceptions import ValidationError

    item = product_range
    validate = service.validate_bound_native_power_source

    def change_after_qualification(*args, **kwargs):
        evidence = validate(*args, **kwargs)
        if fault == "native-generation":
            item.case.row.resource_generation = uuid4()
            item.case.row.save(update_fields=["resource_generation"])
        elif fault == "product-assignment":
            CTFParticipant.objects.filter(pk=item.subject.pk).update(range_instance_id=4242)
        elif fault == "retired-config":
            ParticipantControlConfiguration.objects.filter(pk=item.config.id).update(retired_at=timezone.now())
        else:
            RaesPackageSource.objects.filter(pk=item.source.pk).update(owner_principal_uuid=uuid4())
        return evidence

    monkeypatch.setattr(service, "validate_bound_native_power_source", change_after_qualification)
    with pytest.raises(ValidationError):
        bind(item)
    assert not ParticipantControlBinding.objects.exists()


def test_existing_owner_input_recovers_same_run_during_pending_native_work(product_range):
    from django.db import transaction

    from cms.models import ParticipantControlBinding
    from cms.services import prepare_native_control_binding

    item = product_range
    bound = bind(item)
    item.case.row.status = "pausing"
    item.case.row.save(update_fields=["status"])
    admission = prepare_native_control_binding(item.case.credential, bound.id)
    assert admission.view == bound
    assert admission.native.input.compiler.context == item.case.context
    with transaction.atomic():
        admission.fence()
    assert ParticipantControlBinding.objects.count() == 1


def test_existing_binding_admission_still_fences_product_assignment(product_range):
    from django.db import transaction

    from cms.services import prepare_native_control_binding
    from ctf.models import CTFParticipant
    from shared.exceptions import ValidationError

    item = product_range
    bound = bind(item)
    admission = prepare_native_control_binding(item.case.credential, bound.id)
    CTFParticipant.objects.filter(pk=item.subject.pk).update(range_instance_id=4242)
    with pytest.raises(ValidationError), transaction.atomic():
        admission.fence()


def test_expired_native_lease_prevents_binding_admission(product_range):
    from cms.models import ParticipantControlBinding
    from shared.exceptions import ValidationError

    item = product_range
    item.instance.expires_at = timezone.now() - timedelta(seconds=1)
    item.instance.maximum_expires_at = timezone.now() + timedelta(hours=1)
    item.instance.save(update_fields=["expires_at", "maximum_expires_at"])
    with pytest.raises(ValidationError):
        bind(item)
    assert not ParticipantControlBinding.objects.exists()


def test_lease_expiry_after_preparation_prevents_new_effect_admission(product_range, monkeypatch):
    from django.db import transaction

    from cms.models import RangeInstance
    from cms.services import prepare_native_control_binding
    from shared.exceptions import ValidationError

    item = product_range
    now = timezone.now()
    RangeInstance.objects.filter(pk=item.instance.pk).update(
        expires_at=now + timedelta(minutes=1), maximum_expires_at=now + timedelta(hours=1)
    )
    bound = bind(item)
    admission = prepare_native_control_binding(item.case.credential, bound.id)
    monkeypatch.setattr("cms.services._participant_control_input.timezone.now", lambda: now + timedelta(minutes=2))
    with pytest.raises(ValidationError), transaction.atomic():
        admission.fence()

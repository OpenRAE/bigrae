"""Native invocation permission is bound to one live Job and consumed once."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from tests.engine.services.test_native_participant_dispatch import (
    _admit,
    _release,
    compiled_native,
    native_action,
    tenant,
)
from tests.engine.services.test_native_participant_reservation import _reserve

__all__ = ["compiled_native", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def test_prepared_invocation_commits_without_remote_calls_under_product_locks(launched, monkeypatch):
    from engine.services import begin_prepared_native_power_invocation, prepare_native_power_invocation

    prepared = prepare_native_power_invocation(
        attempt_id=launched.attempt_id,
        action_id=UUID(launched.action.action_id),
        member_ref="provision.node.web#0",
        control_cut_digest=launched.action.control_cut_digest,
        token=SecretStr("fixture.bound.token"),
    )
    calls = launched.authentication.create_token_review.call_count

    def unexpected_remote_call(*args, **kwargs):
        raise AssertionError("Remote admission must precede product SQL locks")

    monkeypatch.setattr("engine.services._launch_authority.admit_launch_authority", unexpected_remote_call)
    grant = begin_prepared_native_power_invocation(prepared)
    assert grant.operation_id == launched.operation
    assert launched.authentication.create_token_review.call_count == calls


def test_prepared_invocation_rechecks_revoked_local_proof(launched):
    from engine.models import ParticipantPowerInvocation
    from engine.services import begin_prepared_native_power_invocation, prepare_native_power_invocation

    prepared = prepare_native_power_invocation(
        attempt_id=launched.attempt_id,
        action_id=UUID(launched.action.action_id),
        member_ref="provision.node.web#0",
        control_cut_digest=launched.action.control_cut_digest,
        token=SecretStr("fixture.bound.token"),
    )
    launched.case.actor.is_active = False
    launched.case.actor.save(update_fields=["is_active"])
    with pytest.raises(ValueError):
        begin_prepared_native_power_invocation(prepared)
    assert not ParticipantPowerInvocation.objects.exists()


def test_job_routing_authenticates_before_returning_private_owner_coordinates(launched):
    from engine.models import ParticipantPowerInvocation
    from engine.services import authenticate_native_power_operation

    route = authenticate_native_power_operation(launched.operation, SecretStr("fixture.bound.token"))
    assert route.action_id == UUID(launched.action.action_id)
    assert route.coordinates == launched.action.coordinates
    assert route.operation_id == launched.operation
    assert launched.authentication.create_token_review.call_count == 1
    assert not ParticipantPowerInvocation.objects.exists()


def test_foreign_job_cannot_obtain_owner_routing_coordinates(launched):
    from engine.services import authenticate_native_power_operation

    launched.authentication.create_token_review.return_value.status.audiences = ["foreign-audience"]
    with pytest.raises(ValueError, match="Native participant invocation unavailable"):
        authenticate_native_power_operation(launched.operation, SecretStr("fixture.bound.token"))


def test_native_owner_observes_open_call_exclusion_until_verified_completion(launched):
    from engine.services import native_participant_power_unresolved

    assert not native_participant_power_unresolved(launched.action.coordinates)
    grant = begin(launched)
    assert native_participant_power_unresolved(launched.action.coordinates)
    finish(launched, grant.invocation_id)
    assert not native_participant_power_unresolved(launched.action.coordinates)


@pytest.fixture
def launched(native_action, monkeypatch, settings):
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "synthetic-native-provisioner"
    case, action = native_action
    operation = _reserve(case, action)
    portable = _admit(case, action)
    _release(case, action, portable)
    return install_workload(case, action, operation, monkeypatch)


def install_workload(case, action, operation, monkeypatch):
    """Project synthetic Kubernetes wire responses around one real outbox launch."""
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from shared.cloud.kubernetes import KubernetesTaskRunner
    from tests.shared.cloud.test_kubernetes_task_runner import _profile

    command = Command()
    from engine.models import ProvisionerLaunchIntent

    retained = ProvisionerLaunchIntent.objects.get(operation_id=operation)
    intent = command._claim_next(intent_id=retained.intent_id)
    expected = intent.executing_workload
    namespace, job_name = expected["namespace"], expected["job_name"]
    command._record_success(intent, namespace + "/" + job_name)
    account = expected["effective_service_account_name"]
    pod_spec = NS(
        service_account_name=account,
        containers=[NS(name=expected["container_name"], image=expected["image"], args=expected["command"])],
    )
    job_spec = deepcopy(pod_spec)
    job_spec.service_account_name = expected["service_account_name"]
    # Kubernetes defaults an omitted service account in both live projections.
    if not job_spec.service_account_name:
        job_spec.service_account_name = "default"
    job = NS(
        metadata=NS(
            name=job_name,
            namespace=namespace,
            uid="fixture-job",
            deletion_timestamp=None,
            annotations={"shifter.dev/task-identity": expected["task_identity"]},
        ),
        spec=NS(template=NS(spec=job_spec)),
        status=NS(succeeded=0, failed=0),
    )
    pod = NS(
        metadata=NS(
            name="fixture-pod",
            namespace=namespace,
            uid="fixture-pod-uid",
            deletion_timestamp=None,
            owner_references=[
                NS(api_version="batch/v1", kind="Job", name=job_name, uid="fixture-job", controller=True)
            ],
        ),
        spec=pod_spec,
        status=NS(
            phase="Running",
            container_statuses=[
                NS(
                    name=expected["container_name"],
                    image_id=expected["image"],
                    container_id="containerd://synthetic-container",
                    state=NS(running=NS()),
                )
            ],
        ),
    )
    authentication, core, batch = Mock(), Mock(), Mock()
    authentication.create_token_review.return_value = NS(
        status=NS(
            authenticated=True,
            audiences=["shifter-native-participant-invocation"],
            error=None,
            user=NS(
                username=f"system:serviceaccount:{namespace}:{account}",
                uid="fixture-account",
                extra={
                    "authentication.kubernetes.io/pod-name": ["fixture-pod"],
                    "authentication.kubernetes.io/pod-uid": ["fixture-pod-uid"],
                },
            ),
        )
    )
    core.read_namespaced_pod.return_value = pod
    batch.read_namespaced_job.return_value = job
    client = NS(AuthenticationV1Api=Mock(return_value=authentication))
    runner = KubernetesTaskRunner(_profile())
    runner._load_kubernetes_api = Mock(return_value=(batch, core, client, RuntimeError))
    monkeypatch.setattr("shared.cloud.get_task_runner", lambda: runner)
    return NS(
        case=case,
        action=action,
        operation=operation,
        pod=pod,
        job=job,
        authentication=authentication,
        attempt_id=uuid4(),
    )


def begin(item, *, member="provision.node.web#0", cut=None):
    from engine.services._native_participant_invocation import begin_native_power_invocation

    return begin_native_power_invocation(
        attempt_id=item.attempt_id,
        action_id=UUID(item.action.action_id),
        member_ref=member,
        control_cut_digest=cut or item.action.control_cut_digest,
        token=SecretStr("fixture.bound.token"),
    )


def test_live_workload_receives_one_exact_member_grant(launched):
    from engine.models import ParticipantPowerInvocation
    from shared.native_participant import native_power_invocation_id

    grant = begin(launched)
    assert grant.operation_id == launched.operation
    assert grant.invocation_id == native_power_invocation_id(launched.operation, grant.member_ref)
    assert grant.member_ref == "provision.node.web#0"
    assert grant.target.instance_name == "synthetic-web"
    assert grant.incarnation.instance_identity == "123"
    saved = ParticipantPowerInvocation.objects.get(invocation_id=grant.invocation_id)
    assert saved.pod_uid == "fixture-pod-uid"
    assert saved.closed_at is None
    with pytest.raises(ValueError):
        begin(launched)
    assert ParticipantPowerInvocation.objects.count() == 1


@pytest.mark.parametrize("fault", ["member", "cut", "authority", "pod", "job", "audience"])
def test_unproved_invocation_creates_no_grant(launched, fault):
    from engine.models import ParticipantPowerInvocation

    member, cut = "provision.node.web#0", None
    if fault == "member":
        member = "provision.node.foreign#0"
    elif fault == "cut":
        cut = "sha256:" + "f" * 64
    elif fault == "authority":
        launched.case.actor.policy_principals.clear()
    elif fault == "pod":
        launched.pod.metadata.uid = "replacement"
    elif fault == "job":
        launched.job.metadata.uid = "replacement"
    else:
        launched.authentication.create_token_review.return_value.status.audiences = ["other"]
    with pytest.raises((ValueError, PermissionError)):
        begin(launched, member=member, cut=cut)
    assert not ParticipantPowerInvocation.objects.exists()


@pytest.mark.parametrize("field", ["resource_generation", "provisioner_operation_id", "owner_principal_uuid"])
def test_active_grant_excludes_generation_or_custody_replacement(launched, field):
    from django.db import IntegrityError, transaction

    from engine.models import Range

    begin(launched)
    with pytest.raises(IntegrityError), transaction.atomic():
        Range.objects.filter(pk=launched.case.row.pk).update(**{field: uuid4()})


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", UUID(int=7)),
        ("container_id", "replacement-container"),
        ("pod_uid", "replacement-pod"),
        ("job_uid", "replacement-job"),
        ("permission_issued", False),
        ("member_ref", "provision.node.other#0"),
    ],
)
def test_consumed_call_identity_cannot_be_rewritten(launched, field, value):
    from django.db import IntegrityError, transaction

    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    with pytest.raises(IntegrityError), transaction.atomic():
        ParticipantPowerInvocation.objects.filter(pk=grant.invocation_id).update(**{field: value})


def test_permission_completion_is_irreversible(launched):
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    finish(launched, grant.invocation_id)
    for value in (None, timezone.now()):
        with pytest.raises(IntegrityError), transaction.atomic():
            ParticipantPowerInvocation.objects.filter(pk=grant.invocation_id).update(closed_at=value)


def test_open_call_allows_member_status_but_refuses_replacement_or_extra_identity(launched):
    from django.db import IntegrityError, transaction

    from engine.models import Range

    begin(launched)
    row = launched.case.row
    members = deepcopy(row.provisioned_instances)
    members[0]["status"] = "failed"
    Range.objects.filter(pk=row.pk).update(provisioned_instances=members)
    row.refresh_from_db()
    assert row.provisioned_instances[0]["status"] == "failed"
    for field, value in [("instance_id", "replacement"), ("unexpected_identity", "extra")]:
        changed = deepcopy(members)
        changed[0][field] = value
        with pytest.raises(IntegrityError), transaction.atomic():
            Range.objects.filter(pk=row.pk).update(provisioned_instances=changed)


def test_native_grant_guard_does_not_interpret_uncontrolled_historical_projections(compiled_native):
    from engine.models import Range

    Range.objects.filter(pk=compiled_native.row.pk).update(provisioned_instances={"historical": "projection"})
    compiled_native.row.refresh_from_db()
    assert compiled_native.row.provisioned_instances == {"historical": "projection"}


def test_original_completion_attempt_and_container_are_independently_bound(launched):
    from engine.models import ParticipantPowerInvocation
    from engine.services import finish_native_power_invocation

    grant = begin(launched)
    with pytest.raises(ValueError):
        finish_native_power_invocation(
            invocation_id=grant.invocation_id,
            attempt_id=uuid4(),
            token=SecretStr("fixture.bound.token"),
        )
    launched.pod.status.container_statuses[0].container_id = "containerd://replacement"
    with pytest.raises(ValueError):
        finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None


def test_failed_invocation_audit_rolls_back_permission(launched, monkeypatch):
    from engine.models import ParticipantPowerInvocation

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic invocation audit unavailable")

    monkeypatch.setattr("engine.services._native_participant_invocation.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="invocation audit unavailable"):
        begin(launched)
    assert not ParticipantPowerInvocation.objects.exists()


def test_closed_grant_never_allows_another_call(launched):
    from django.utils import timezone

    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    ParticipantPowerInvocation.objects.filter(pk=grant.invocation_id).update(closed_at=timezone.now())
    with pytest.raises(ValueError):
        begin(launched)


def test_another_unresolved_member_excludes_invocation(launched):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation

    reservation = ParticipantPowerReservation.objects.get(action_id=UUID(launched.action.action_id))
    ParticipantPowerInvocation.objects.create(
        invocation_id=uuid4(),
        reservation=reservation,
        member_ref="provision.node.other#0",
        pod_uid="fixture-pod-uid",
        job_uid="fixture-job",
    )
    with pytest.raises(ValueError):
        begin(launched)


def test_generation_change_during_workload_review_creates_no_grant(launched):
    from engine.models import ParticipantPowerInvocation, Range

    result = launched.authentication.create_token_review.return_value

    def replace_during_review(**kwargs):
        Range.objects.filter(pk=launched.case.row.pk).update(resource_generation=uuid4())
        return result

    launched.authentication.create_token_review.side_effect = replace_during_review
    with pytest.raises(ValueError):
        begin(launched)
    assert not ParticipantPowerInvocation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_simultaneous_acquisitions_consume_only_one_permission(launched):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    from engine.models import ParticipantPowerInvocation

    reviewed = Barrier(2, timeout=10)
    result = launched.authentication.create_token_review.return_value

    def review(**kwargs):
        reviewed.wait()
        return result

    def acquire():
        close_old_connections()
        try:
            return begin(launched)
        except ValueError:
            return None
        finally:
            close_old_connections()

    launched.authentication.create_token_review.side_effect = review
    with ThreadPoolExecutor(max_workers=2) as pool:
        acquired = list(pool.map(lambda _: acquire(), range(2)))
    assert sum(grant is not None for grant in acquired) == 1
    assert ParticipantPowerInvocation.objects.count() == 1


def test_invocation_grant_binds_verb_and_resource_generation(launched):
    grant = begin(launched)
    assert grant.verb == launched.action.verb
    assert grant.resource_generation == launched.action.coordinates.resource_generation


def finish(item, invocation_id):
    from engine.services._native_participant_invocation import finish_native_power_invocation

    return finish_native_power_invocation(
        invocation_id=invocation_id,
        attempt_id=item.attempt_id,
        token=SecretStr("fixture.bound.token"),
    )


def test_verified_worker_can_close_only_its_consumed_permission(launched):
    from engine.models import ParticipantPowerInvocation, Range

    grant = begin(launched)
    finish(launched, grant.invocation_id)
    saved = ParticipantPowerInvocation.objects.get(pk=grant.invocation_id)
    assert saved.closed_at is not None
    finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at == saved.closed_at
    with pytest.raises(ValueError):
        begin(launched)
    Range.objects.filter(pk=launched.case.row.pk).update(resource_generation=uuid4())


def test_worker_cessation_remains_recordable_after_initiator_revocation(launched):
    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    launched.case.actor.policy_principals.clear()
    finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is not None


def test_original_worker_can_record_cessation_after_installation_image_changes(launched, settings):
    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    settings.ENGINE_TASK_DEFINITION = "example.test/replacement-native-provisioner@sha256:" + "f" * 64
    finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is not None


def test_authenticated_routing_and_cessation_never_decrypt_private_parameters(launched, settings):
    from cryptography.fernet import Fernet

    from engine.models import ParticipantPowerInvocation
    from engine.services import authenticate_native_power_operation

    grant = begin(launched)
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    route = authenticate_native_power_operation(launched.operation, SecretStr("fixture.bound.token"))
    assert route.coordinates == launched.action.coordinates
    finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is not None


def test_installation_image_drift_cannot_grant_a_new_call(launched, settings):
    from engine.models import ParticipantPowerInvocation

    settings.ENGINE_TASK_DEFINITION = "example.test/replacement-native-provisioner@sha256:" + "f" * 64
    with pytest.raises(ValueError):
        begin(launched)
    assert not ParticipantPowerInvocation.objects.exists()


def test_replacement_worker_cannot_close_an_uncertain_call(launched):
    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    launched.pod.metadata.uid = "replacement-pod"
    launched.authentication.create_token_review.return_value.status.user.extra[
        "authentication.kubernetes.io/pod-uid"
    ] = ["replacement-pod"]
    with pytest.raises(ValueError):
        finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None


def test_failed_completion_audit_retains_exclusion(launched, monkeypatch):
    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic completion audit unavailable")

    monkeypatch.setattr("engine.services._native_participant_invocation.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="completion audit unavailable"):
        finish(launched, grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None


def test_mismatched_pending_verb_has_no_call_permission(launched):
    from engine.models import ParticipantPowerInvocation, Range

    status = "resuming" if launched.action.verb == "pause" else "pausing"
    Range.objects.filter(pk=launched.case.row.pk).update(status=status)
    with pytest.raises(ValueError):
        begin(launched)
    assert not ParticipantPowerInvocation.objects.exists()
